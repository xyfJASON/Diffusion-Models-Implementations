import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import math
import argparse
from omegaconf import OmegaConf

import torch
import accelerate
from torchvision.utils import save_image

import diffusions
from utils.logger import get_logger
from utils.load import load_weights
from utils.misc import image_norm_to_float, instantiate_from_config, amortize


def get_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-c', '--config', type=str, required=True,
        help='Path to inference configuration file',
    )
    parser.add_argument(
        '--seed', type=int, default=2022,
        help='Set random seed',
    )
    parser.add_argument(
        '--weights', type=str, required=True,
        help='Path to pretrained model weights',
    )
    parser.add_argument(
        '--guidance_scale', type=float, required=True,
        help='Guidance scale. 0 for unconditional generation, '
             '1 for non-guided generation, >1 for guided generation',
    )
    parser.add_argument(
        '--class_ids', type=int, nargs='+', default=None,
        help='Which class IDs to sample. '
             'If not provided, will sample all the classes',
    )
    parser.add_argument(
        '--n_samples_each_class', type=int, required=True,
        help='Number of samples in each class',
    )
    parser.add_argument(
        '--save_dir', type=str, required=True,
        help='Path to directory saving samples',
    )
    parser.add_argument(
        '--batch_size', type=int, default=500,
        help='Batch size on each process',
    )
    # arguments for all diffusers
    parser.add_argument(
        '--sampler', type=str, choices=['ddpm', 'ddim'], default='ddpm',
        help='Type of sampler',
    )
    parser.add_argument(
        '--respace_type', type=str, default='uniform',
        help='Type of respaced timestep sequence',
    )
    parser.add_argument(
        '--respace_steps', type=int, default=None,
        help='Length of respaced timestep sequence',
    )
    # arguments for ddpm
    parser.add_argument(
        '--var_type', type=str, default=None,
        help='Type of variance of the reverse process',
    )
    # arguments for ddim
    parser.add_argument(
        '--ddim_eta', type=float, default=0.0,
        help='Parameter eta in DDIM sampling',
    )
    return parser


if __name__ == '__main__':
    # PARSE ARGS AND CONFIGS
    args, unknown_args = get_parser().parse_known_args()
    unknown_args = [(a[2:] if a.startswith('--') else a) for a in unknown_args]
    unknown_args = [f'{k}={v}' for k, v in zip(unknown_args[::2], unknown_args[1::2])]
    conf = OmegaConf.load(args.config)
    conf = OmegaConf.merge(conf, OmegaConf.from_dotlist(unknown_args))

    # INITIALIZE ACCELERATOR
    accelerator = accelerate.Accelerator()
    device = accelerator.device
    print(f'Process {accelerator.process_index} using device: {device}')
    accelerator.wait_for_everyone()

    # INITIALIZE LOGGER
    logger = get_logger(
        use_tqdm_handler=True,
        is_main_process=accelerator.is_main_process,
    )

    # SET SEED
    accelerate.utils.set_seed(args.seed, device_specific=True)
    logger.info('=' * 19 + ' System Info ' + '=' * 18)
    logger.info(f'Number of processes: {accelerator.num_processes}')
    logger.info(f'Distributed type: {accelerator.distributed_type}')
    logger.info(f'Mixed precision: {accelerator.mixed_precision}')

    accelerator.wait_for_everyone()

    # BUILD DIFFUSER
    if args.sampler == 'ddpm':
        diffuser = diffusions.ddpm.DDPMCFG(
            total_steps=conf.diffusion.params.total_steps,
            beta_schedule=conf.diffusion.params.beta_schedule,
            beta_start=conf.diffusion.params.beta_start,
            beta_end=conf.diffusion.params.beta_end,
            objective=conf.diffusion.params.objective,
            var_type=args.var_type or conf.diffusion.params.get('var_type', None),
            respace_type=None if args.respace_steps is None else args.respace_type,
            respace_steps=args.respace_steps or conf.diffusion.params.total_steps,
            device=device,
            guidance_scale=args.guidance_scale,
        )
    elif args.sampler == 'ddim':
        diffuser = diffusions.ddim.DDIMCFG(
            total_steps=conf.diffusion.params.total_steps,
            beta_schedule=conf.diffusion.params.beta_schedule,
            beta_start=conf.diffusion.params.beta_start,
            beta_end=conf.diffusion.params.beta_end,
            objective=conf.diffusion.params.objective,
            respace_type=None if args.respace_steps is None else args.respace_type,
            respace_steps=args.respace_steps or conf.diffusion.params.total_steps,
            eta=args.ddim_eta,
            device=device,
            guidance_scale=args.guidance_scale,
        )
    else:
        raise ValueError(f'Unknown sampler: {args.sampler}')

    # BUILD MODEL
    model = instantiate_from_config(conf.model)

    # LOAD WEIGHTS
    weights = load_weights(args.weights)
    model.load_state_dict(weights)
    logger.info('=' * 19 + ' Model Info ' + '=' * 19)
    logger.info(f'Successfully load model from {args.weights}')
    logger.info('=' * 50)

    # PREPARE FOR DISTRIBUTED MODE AND MIXED PRECISION
    model = accelerator.prepare(model)
    model.eval()

    accelerator.wait_for_everyone()

    @torch.no_grad()
    def sample():
        img_shape = (conf.data.img_channels, conf.data.params.img_size, conf.data.params.img_size)
        bspp = min(args.batch_size, math.ceil(args.n_samples_each_class / accelerator.num_processes))
        class_ids = args.class_ids
        if args.class_ids is None:
            class_ids = range(conf.data.num_classes)
        logger.info(f'Will sample {args.n_samples_each_class} images for each of the following class IDs: {class_ids}')

        for c in class_ids:
            os.makedirs(os.path.join(args.save_dir, f'class{c}'), exist_ok=True)
            idx = 0
            logger.info(f'Sampling class {c}')
            folds = amortize(args.n_samples_each_class, bspp * accelerator.num_processes)
            for i, bs in enumerate(folds):
                init_noise = torch.randn((bs, *img_shape), device=device)
                labels = torch.full((bs, ), fill_value=c, device=device)
                samples = diffuser.sample(
                    model=accelerator.unwrap_model(model), init_noise=init_noise, model_kwargs=dict(y=labels),
                    tqdm_kwargs=dict(desc=f'Fold {i}/{len(folds)}', disable=not accelerator.is_main_process),
                ).clamp(-1, 1)
                samples = accelerator.gather(samples)[:bs]
                if accelerator.is_main_process:
                    for x in samples:
                        x = image_norm_to_float(x).cpu()
                        save_image(x, os.path.join(args.save_dir, f'class{c}', f'{idx}.png'), nrow=1)
                        idx += 1

    # START SAMPLING
    logger.info('Start sampling...')
    os.makedirs(args.save_dir, exist_ok=True)
    logger.info(f'Samples will be saved to {args.save_dir}')
    sample()
    logger.info(f'Sampled images are saved to {args.save_dir}')
    logger.info('End of sampling')
