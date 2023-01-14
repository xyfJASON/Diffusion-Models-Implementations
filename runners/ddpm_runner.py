import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
import tqdm
import math

import torch
import torch.nn as nn
import torch.distributed as dist
from torch.nn.parallel import DistributedDataParallel as DDP
from torch.utils.data import DataLoader
from torch.utils.data.distributed import DistributedSampler
from torchvision.utils import save_image

import models
import diffusions
from datasets import build_dataset
from utils.logger import MessageLogger, AverageMeter
from utils.optimizer import build_optimizer, optimizer_to_device
from utils.dist import get_dist_info, master_only, init_dist, reduce_tensor
from utils.misc import get_device, init_seeds, check_freq, get_bare_model, create_exp_dir, dict2namespace


class DDPMRunner:
    def __init__(self, args, config):
        self.config = config

        # INITIALIZE DISTRIBUTED MODE
        init_dist()
        self.dist_info = dict2namespace(get_dist_info())
        self.device = get_device(self.dist_info)

        # CREATE LOG DIRECTORY
        if args.func == 'train' and self.dist_info.is_master:
            self.exp_dir = create_exp_dir(args, config)
        else:
            self.exp_dir = None
        if self.dist_info.is_dist:
            object_list = [self.exp_dir]
            dist.broadcast_object_list(object_list, src=0)
            self.exp_dir = object_list[0]

        # INITIALIZE SEEDS
        init_seeds(getattr(self.config, 'seed', 2022) + self.dist_info.global_rank)

        # INITIALIZE LOGGER
        self.logger = MessageLogger(
            log_root=self.exp_dir,
            print_freq=self.config.train.print_freq.by_step if args.func == 'train' else 0,
        )
        self.logger.info(f'Device: {self.device}')
        self.logger.info(f'Log directory: {self.exp_dir}')

        # DATA
        if args.func == 'train':
            self.dataset = build_dataset(
                dataset=self.config.data.dataset,
                dataroot=self.config.data.dataroot,
                img_size=self.config.data.img_size,
                split='train',
            )
            self.train_loader = DataLoader(
                dataset=self.dataset,
                batch_size=self.config.train.batch_size,
                shuffle=None if self.dist_info.is_dist else True,
                sampler=DistributedSampler(self.dataset, shuffle=True) if self.dist_info.is_dist else None,
                num_workers=4,
                pin_memory=True,
            )
            self.logger.info(f'Size of dataset: {len(self.dataset)}')
            self.logger.info(f'Each epoch has {len(self.train_loader)} iterations')

        # BUILD MODELS, OPTIMIZERS AND SCHEDULERS
        self.DiffusionModel = diffusions.DDPM(
            total_steps=self.config.ddpm.total_steps,
            beta_schedule=self.config.ddpm.beta_schedule,
            beta_start=self.config.ddpm.beta_start,
            beta_end=self.config.ddpm.beta_end,
            objective=self.config.ddpm.objective,
            var_type=self.config.ddpm.var_type,
        )
        self.model = models.UNet(
            img_channels=self.config.data.img_channels,
            dim=self.config.model.dim,
            dim_mults=self.config.model.dim_mults,
            use_attn=self.config.model.use_attn,
            num_res_blocks=self.config.model.num_res_blocks,
            resblock_groups=self.config.model.resblock_groups,
            attn_groups=self.config.model.attn_groups,
            attn_heads=self.config.model.attn_heads,
            dropout=self.config.model.dropout,
        )
        self.model.to(device=self.device)
        self.ema = models.EMA(self.model, decay=self.config.model.ema_decay)
        if args.func == 'train':
            self.optimizer = build_optimizer(self.model.parameters(), config=self.config.train.optimizer)

        # LOAD PRETRAINED WEIGHTS / RESUME
        if args.func == 'train':
            if getattr(self.config.train, 'pretrained', None):
                self.load_model(self.config.train.pretrained)
            self.start_epoch = 0
            self.global_step = -1
            if getattr(self.config.train, 'resume', None):
                self.load_ckpt(self.config.train.resume)
        else:
            cfg = getattr(config, args.func)
            if getattr(cfg, 'model_path', None):
                self.load_model(cfg.model_path, load_ema=cfg.load_ema)

        # DISTRIBUTED
        if self.dist_info.is_dist:
            self.model = DDP(
                module=self.model,
                device_ids=[self.dist_info.local_rank],
                output_device=self.dist_info.local_rank,
            )

        # TEST SAMPLES
        if args.func == 'train':
            if self.config.train.n_samples % self.dist_info.world_size != 0:
                raise ValueError('Number of samples should be divisible by WORLD_SIZE!')

    def load_model(self, model_path: str, load_ema: bool = False):
        ckpt = torch.load(model_path, map_location='cpu')
        self.model.load_state_dict(ckpt['ema']['shadow'] if load_ema else ckpt['model'])
        self.model.to(device=self.device)
        self.logger.info(f'Successfully load model from {model_path}')

        self.ema.load_state_dict(ckpt['ema'], device=self.device)
        self.logger.info(f'Successfully load ema from {model_path}')

    @master_only
    def save_model(self, save_path: str):
        state_dicts = dict(
            model=get_bare_model(self.model).state_dict(),
            ema=self.ema.state_dict(),
        )
        torch.save(state_dicts, save_path)

    def load_ckpt(self, ckpt_path: str):
        self.logger.info(f'Resume from {ckpt_path}')
        self.load_model(ckpt_path)
        ckpt = torch.load(ckpt_path, map_location='cpu')
        self.optimizer.load_state_dict(ckpt['optimizer'])
        optimizer_to_device(self.optimizer, self.device)
        self.start_epoch = ckpt['epoch'] + 1
        self.global_step = ckpt['global_step']
        self.logger.info(f'Restart at epoch {self.start_epoch}')

    @master_only
    def save_ckpt(self, save_path: str, epoch: int):
        state_dicts = dict(
            model=get_bare_model(self.model).state_dict(),
            ema=self.ema.state_dict(),
            optimizer=self.optimizer.state_dict(),
            epoch=epoch,
            global_step=self.global_step,
        )
        torch.save(state_dicts, save_path)

    def train(self):
        self.logger.info('Start training...')

        # start of epoch
        for ep in range(self.start_epoch, self.config.train.epochs):
            self.model.train()
            if self.dist_info.is_dist:
                self.train_loader.sampler.set_epoch(ep)

            # start of iter
            loss_meter = AverageMeter()
            pbar = tqdm.tqdm(self.train_loader, desc=f'Epoch {ep}', ncols=120, disable=not self.dist_info.is_master)
            for it, X in enumerate(pbar):
                self.model.train()

                X = X[0] if isinstance(X, (tuple, list)) else X
                X = X.to(device=self.device, dtype=torch.float32)

                t = torch.randint(self.config.ddpm.total_steps, (X.shape[0], ), device=self.device).long()
                loss = self.DiffusionModel.loss_func(self.model, X0=X, t=t)
                self.optimizer.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=1.)
                self.optimizer.step()
                self.ema.update()

                self.global_step += 1
                loss = reduce_tensor(loss.detach())
                loss_meter.update(loss.item())
                pbar.set_postfix({'loss': loss_meter.avg})
                train_status = dict(loss=loss.item())
                self.logger.track_status('Train', train_status, global_step=self.global_step, epoch=ep, iteration=it)
                if check_freq(getattr(self.config.train.save_freq, 'by_step', 0), self.global_step):
                    self.save_ckpt(os.path.join(self.exp_dir, 'ckpt', f'epoch{ep}_iter{it}.pt'), epoch=ep)
                if check_freq(getattr(self.config.train.sample_freq, 'by_step', 0), self.global_step):
                    self.ema.apply_shadow()
                    self.sample_during_training(os.path.join(self.exp_dir, 'samples', f'epoch{ep}_iter{it}.png'))
                    self.ema.restore()
                if self.dist_info.is_dist:
                    dist.barrier()
            pbar.close()
            # end of iter

            if check_freq(getattr(self.config.train.save_freq, 'by_epoch', 0), ep):
                self.save_ckpt(os.path.join(self.exp_dir, 'ckpt', f'epoch{ep}.pt'), epoch=ep)
            if check_freq(getattr(self.config.train.sample_freq, 'by_epoch', 0), ep):
                self.ema.apply_shadow()
                self.sample_during_training(os.path.join(self.exp_dir, 'samples', f'epoch{ep}.png'))
                self.ema.restore()
            if self.dist_info.is_dist:
                dist.barrier()
        # end of epoch

        self.save_model(os.path.join(self.exp_dir, 'model.pt'))
        self.logger.info('End of traning')
        self.logger.close()

    @torch.no_grad()
    def sample_during_training(self, savepath: str):
        cfg = self.config.train
        num_each_device = cfg.n_samples // self.dist_info.world_size
        model = get_bare_model(self.model).eval()

        samples = []
        total = math.ceil(num_each_device / cfg.batch_size)
        img_shape = (self.config.data.img_channels, self.config.data.img_size, self.config.data.img_size)
        for i in range(total):
            n = min(cfg.batch_size, num_each_device - i * cfg.batch_size)
            init_noise = torch.randn((n, *img_shape), device=self.device)
            X = self.DiffusionModel.sample(
                model=model,
                init_noise=init_noise,
                with_tqdm=self.dist_info.is_master,
                desc=f'Sampling({i+1}/{total})',
                ncols=120,
            ).clamp(-1, 1)
            samples.append(X)
        samples = torch.cat(samples, dim=0)
        if self.dist_info.is_dist:
            sample_list = [torch.Tensor() for _ in range(self.dist_info.world_size)]
            dist.all_gather_object(sample_list, samples)
            samples = torch.cat(sample_list, dim=0)
        samples = samples.cpu()
        if self.dist_info.is_master:
            nrow = math.floor(math.sqrt(cfg.n_samples))
            save_image(samples, savepath, nrow=nrow, normalize=True, value_range=(-1, 1))

    @torch.no_grad()
    def sample(self):
        cfg = self.config.sample
        self.logger.info('Start sampling...')
        self.logger.info(f'Samples will be saved to {cfg.save_dir}')
        os.makedirs(cfg.save_dir, exist_ok=True)
        num_each_device = cfg.n_samples // self.dist_info.world_size
        model = get_bare_model(self.model).eval()

        total = math.ceil(num_each_device / cfg.batch_size)
        img_shape = (self.config.data.img_channels, self.config.data.img_size, self.config.data.img_size)
        for i in range(total):
            n = min(cfg.batch_size, num_each_device - i * cfg.batch_size)
            init_noise = torch.randn((n, *img_shape), device=self.device)
            X = self.DiffusionModel.sample(
                model=model,
                init_noise=init_noise,
                with_tqdm=self.dist_info.is_master,
                desc=f'Sampling({i+1}/{total})',
                ncols=120,
            ).clamp(-1, 1)
            for j, x in enumerate(X):
                idx = self.dist_info.global_rank * num_each_device + i * cfg.batch_size + j
                save_image(
                    tensor=x.cpu(), fp=os.path.join(cfg.save_dir, f'{idx}.png'),
                    nrow=1, normalize=True, value_range=(-1, 1),
                )
        self.logger.info(f"Sampled images are saved to {cfg.save_dir}")
        self.logger.info('End of sampling')

    @torch.no_grad()
    def sample_denoise(self):
        cfg = self.config.sample_denoise
        self.logger.info('Start sampling...')
        self.logger.info(f'Samples will be saved to {cfg.save_dir}')
        os.makedirs(cfg.save_dir, exist_ok=True)
        num_each_device = cfg.n_samples // self.dist_info.world_size
        model = get_bare_model(self.model).eval()

        total = math.ceil(num_each_device / cfg.batch_size)
        img_shape = (self.config.data.img_channels, self.config.data.img_size, self.config.data.img_size)
        freq = self.config.ddpm.total_steps // cfg.n_denoise
        for i in range(total):
            n = min(cfg.batch_size, num_each_device - i * cfg.batch_size)
            init_noise = torch.randn((n, *img_shape), device=self.device)
            sample_generator = self.DiffusionModel.sample_loop(
                model=model,
                init_noise=init_noise,
                with_tqdm=self.dist_info.is_master,
                desc=f'Sampling({i+1}/{total})',
                ncols=120,
            )
            X = []
            for timestep, out in enumerate(sample_generator):
                if (self.config.ddpm.total_steps - timestep - 1) % freq == 0:
                    X.append(out['sample'])
            X = torch.stack(X, dim=1).clamp(-1, 1)
            for j, x in enumerate(X):
                idx = self.dist_info.global_rank * num_each_device + i * cfg.batch_size + j
                save_image(
                    tensor=x.cpu(), fp=os.path.join(cfg.save_dir, f'{idx}.png'),
                    nrow=len(x), normalize=True, value_range=(-1, 1),
                )
        self.logger.info(f"Sampled images are saved to {cfg.save_dir}")
        self.logger.info('End of sampling')

    @torch.no_grad()
    def sample_progressive(self):
        cfg = self.config.sample_progressive
        self.logger.info('Start sampling...')
        self.logger.info(f'Samples will be saved to {cfg.save_dir}')
        os.makedirs(cfg.save_dir, exist_ok=True)
        num_each_device = cfg.n_samples // self.dist_info.world_size
        model = get_bare_model(self.model).eval()

        total = math.ceil(num_each_device / cfg.batch_size)
        img_shape = (self.config.data.img_channels, self.config.data.img_size, self.config.data.img_size)
        freq = self.config.ddpm.total_steps // cfg.n_progressive
        for i in range(total):
            n = min(cfg.batch_size, num_each_device - i * cfg.batch_size)
            init_noise = torch.randn((n, *img_shape), device=self.device)
            sample_generator = self.DiffusionModel.sample_loop(
                model=model,
                init_noise=init_noise,
                with_tqdm=self.dist_info.is_master,
                desc=f'Sampling({i+1}/{total})',
                ncols=120,
            )
            X = []
            for timestep, out in enumerate(sample_generator):
                if (self.config.ddpm.total_steps - timestep - 1) % freq == 0:
                    X.append(out['pred_X0'])
            X = torch.stack(X, dim=1).clamp(-1, 1)
            for j, x in enumerate(X):
                idx = self.dist_info.global_rank * num_each_device + i * cfg.batch_size + j
                save_image(
                    tensor=x.cpu(), fp=os.path.join(cfg.save_dir, f'{idx}.png'),
                    nrow=len(x), normalize=True, value_range=(-1, 1),
                )
        self.logger.info(f"Sampled images are saved to {cfg.save_dir}")
        self.logger.info('End of sampling')

    @torch.no_grad()
    def sample_skip(self):
        cfg = self.config.sample_skip
        self.logger.info('Start sampling...')
        self.logger.info(f'Samples will be saved to {cfg.save_dir}')
        os.makedirs(cfg.save_dir, exist_ok=True)
        num_each_device = cfg.n_samples // self.dist_info.world_size
        model = get_bare_model(self.model).eval()

        skip = self.config.ddpm.total_steps // cfg.n_timesteps
        timesteps = torch.arange(0, self.config.ddpm.total_steps, skip)
        DiffusionModel = diffusions.DDPMSkip(
            timesteps=timesteps,
            total_steps=self.config.ddpm.total_steps,
            beta_schedule=self.config.ddpm.beta_schedule,
            beta_start=self.config.ddpm.beta_start,
            beta_end=self.config.ddpm.beta_end,
            objective=self.config.ddpm.objective,
            var_type=self.config.ddpm.var_type,
        )

        total = math.ceil(num_each_device / cfg.batch_size)
        img_shape = (self.config.data.img_channels, self.config.data.img_size, self.config.data.img_size)
        for i in range(total):
            n = min(cfg.batch_size, num_each_device - i * cfg.batch_size)
            init_noise = torch.randn((n, *img_shape), device=self.device)
            X = DiffusionModel.sample(
                model=model,
                init_noise=init_noise,
                with_tqdm=self.dist_info.is_master,
                desc=f'Sampling({i+1}/{total})',
                ncols=120,
            ).clamp(-1, 1)

            for j, x in enumerate(X):
                idx = self.dist_info.global_rank * num_each_device + i * cfg.batch_size + j
                save_image(
                    tensor=x.cpu(),
                    fp=os.path.join(cfg.save_dir, f'{idx}.png'),
                    nrow=1, normalize=True, value_range=(-1, 1),
                )
        self.logger.info(f"Sampled images are saved to {cfg.save_dir}")
        self.logger.info('End of sampling')
