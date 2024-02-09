import tqdm
from typing import Dict, Any
from contextlib import contextmanager

import torch
from torch import Tensor, nn as nn

from diffusions.ddpm import DDPM


class DDPMCFG(DDPM):
    def __init__(self, guidance_scale: float = 1., cond_kwarg: str = 'y', *args, **kwargs):
        """Denoising Diffusion Probabilistic Models with Classifier-Free Guidance.

        Args:
            guidance_scale: Strength of guidance. Note we actually use the definition in classifier guidance paper
             instead of classifier-free guidance paper. Specifically, let the former be `s` and latter be `w`, then we
             have `s=w+1`, where `s=0` means unconditional generation, `s=1` means non-guided conditional generation, and
             `s>1` means guided conditional generation. This argument doesn't affect training and can be overridden by sampling functions.

            cond_kwarg: Name of the condition argument passed to model. Default to `y`.

        References:
            [1] Ho, Jonathan, Ajay Jain, and Pieter Abbeel. "Denoising diffusion probabilistic models."
            Advances in neural information processing systems 33 (2020): 6840-6851.

            [2] Ho, Jonathan, and Tim Salimans. "Classifier-free diffusion guidance." arXiv preprint
            arXiv:2207.12598 (2022).

            [3] Dhariwal, Prafulla, and Alexander Nichol. "Diffusion models beat gans on image synthesis." Advances
            in neural information processing systems 34 (2021): 8780-8794.

        """
        super().__init__(*args, **kwargs)
        self.guidance_scale = guidance_scale
        self.cond_kwarg = cond_kwarg

    def sample_loop(
            self, model: nn.Module, init_noise: Tensor,
            var_type: str = None, clip_denoised: bool = None,
            guidance_scale: float = None, uncond_conditioning: Any = None,
            tqdm_kwargs: Dict = None, model_kwargs: Dict = None,
    ):
        if guidance_scale is None:
            guidance_scale = self.guidance_scale
        if tqdm_kwargs is None:
            tqdm_kwargs = dict()
        if self.cond_kwarg not in model_kwargs.keys():
            raise ValueError(f'Condition argument `{self.cond_kwarg}` not found in model_kwargs.')
        uncond_model_kwargs = model_kwargs.copy()
        uncond_model_kwargs[self.cond_kwarg] = uncond_conditioning

        img = init_noise
        sample_seq = self.respaced_seq.tolist()
        sample_seq_prev = [-1] + self.respaced_seq[:-1].tolist()
        pbar = tqdm.tqdm(total=len(sample_seq), **tqdm_kwargs)
        for t, t_prev in zip(reversed(sample_seq), reversed(sample_seq_prev)):
            t_batch = torch.full((img.shape[0], ), t, device=self.device)
            # conditional branch
            model_output_cond = model(img, t_batch, **model_kwargs)
            out_cond = self.p_sample(model_output_cond, img, t, t_prev, var_type, clip_denoised)
            pred_eps_cond = out_cond['pred_eps']
            # unconditional branch
            model_output_uncond = model(img, t_batch, **uncond_model_kwargs)
            out_uncond = self.p_sample(model_output_uncond, img, t, t_prev, var_type, clip_denoised)
            pred_eps_uncond = out_uncond['pred_eps']
            # combine
            pred_eps = (1 - guidance_scale) * pred_eps_uncond + guidance_scale * pred_eps_cond
            with self.hack_objective('pred_eps'):
                out = self.p_sample(pred_eps, img, t, t_prev, var_type, clip_denoised)
            img = out['sample']
            pbar.update(1)
            yield out
        pbar.close()

    def sample(
            self, model: nn.Module, init_noise: Tensor,
            var_type: str = None, clip_denoised: bool = None,
            guidance_scale: float = None, uncond_conditioning: Any = None,
            tqdm_kwargs: Dict = None, model_kwargs: Dict = None,
    ):
        sample = None
        for out in self.sample_loop(
                model, init_noise,
                var_type, clip_denoised,
                guidance_scale, uncond_conditioning,
                tqdm_kwargs, model_kwargs,
        ):
            sample = out['sample']
        return sample

    @contextmanager
    def hack_objective(self, objective: str):
        """Hack objective temporarily."""
        tmp = self.objective
        self.objective = objective
        yield
        self.objective = tmp
