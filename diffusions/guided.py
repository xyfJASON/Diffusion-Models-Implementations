from typing import List, Dict, Callable

import torch
from torch import Tensor
import torch.nn as nn

from diffusions.schedule import get_beta_schedule


class Guided:
    """ Diffusion process with (explicit) guidance

    The idea was first proposed by classifier guidance paper, and can be used for conditions besides
    categorial labels, such as text.

    The guidance can be applied to the predicted eps, or the predicted x0, or the mean of the reverse distribution.
    """
    def __init__(self, betas: Tensor = None, objective: str = 'pred_eps', var_type: str = 'fixed_large'):
        assert objective in ['pred_eps', 'pred_x0']
        self.objective = objective
        self.var_type = var_type

        # Define betas, alphas and related terms
        self.betas = get_beta_schedule() if betas is None else betas
        self.alphas = 1. - self.betas
        self.total_steps = len(self.betas)
        self.alphas_cumprod = torch.cumprod(self.alphas, dim=0)
        self.alphas_cumprod_prev = torch.cat((torch.ones(1, dtype=torch.float64), self.alphas_cumprod[:-1]))

        # q(Xt | X0)
        self.sqrt_alphas_cumprod = torch.sqrt(self.alphas_cumprod)
        self.sqrt_one_minus_alphas_cumprod = torch.sqrt(1. - self.alphas_cumprod)

        # q(X{t-1} | Xt, X0)
        self.posterior_variance = self.betas * (1. - self.alphas_cumprod_prev) / (1. - self.alphas_cumprod)
        self.posterior_log_variance = torch.log(torch.cat([self.posterior_variance[[1]], self.posterior_variance[1:]]))
        self.posterior_mean_coef1 = torch.sqrt(self.alphas_cumprod_prev) * self.betas / (1. - self.alphas_cumprod)
        self.posterior_mean_coef2 = torch.sqrt(self.alphas) * (1. - self.alphas_cumprod_prev) / (1. - self.alphas_cumprod)

        # p(X{t-1} | Xt)
        self.sqrt_recip_alphas_cumprod = torch.sqrt(1. / self.alphas_cumprod)
        self.sqrt_recipm1_alphas_cumprod = torch.sqrt(1. / self.alphas_cumprod - 1.)

    @staticmethod
    def _extract(a: Tensor, t: Tensor):
        """ Extract elements in `a` according to a batch of indices `t`, and reshape it to [bs, 1, 1, 1]
        Args:
            a (Tensor): [T]
            t (Tensor): [bs]
        Returns:
            Tensor of shape [bs, 1, 1, 1]
        """
        a = a.to(device=t.device, dtype=torch.float32)
        return a[t][:, None, None, None]

    def q_sample(self, X0: Tensor, t: Tensor, eps: Tensor = None):
        """ Sample from q(Xt | X0)
        Args:
            X0 (Tensor): [bs, C, H, W]
            t (Tensor): [bs], time steps for each sample in X0, note that different sample may have different t
            eps (Tensor | None): [bs, C, H, W]
        """
        if eps is None:
            eps = torch.randn_like(X0)
        mean = self._extract(self.sqrt_alphas_cumprod, t) * X0
        std = self._extract(self.sqrt_one_minus_alphas_cumprod, t)
        return mean + std * eps

    def q_posterior_mean_variance(self, X0: Tensor, Xt: Tensor, t: Tensor):
        """ Compute mean and variance of q(X{t-1} | Xt, X0)
        Args:
            X0 (Tensor): [bs, C, H, W]
            Xt (Tensor): [bs, C, H, W]
            t (Tensor): [bs], time steps for each sample in X0 and Xt
        """
        mean_t = (self._extract(self.posterior_mean_coef1, t) * X0 +
                  self._extract(self.posterior_mean_coef2, t) * Xt)
        var_t = self._extract(self.posterior_variance, t)
        log_var_t = self._extract(self.posterior_log_variance, t)
        return mean_t, var_t, log_var_t

    def pred_X0_from_eps(self, Xt: Tensor, t: Tensor, eps: Tensor):
        return (self._extract(self.sqrt_recip_alphas_cumprod, t) * Xt -
                self._extract(self.sqrt_recipm1_alphas_cumprod, t) * eps)

    def pred_eps_from_X0(self, Xt: Tensor, t: Tensor, X0: Tensor):
        return ((self._extract(self.sqrt_recip_alphas_cumprod, t) * Xt - X0) /
                self._extract(self.sqrt_recipm1_alphas_cumprod, t))

    def p_mean_variance(self, model: nn.Module, Xt: Tensor, t: Tensor, clip_denoised: bool = True, **model_kwargs):
        """ Compute mean and variance of p(X{t-1} | Xt)
        Args:
            model (nn.Module): UNet model
            Xt (Tensor): [bs, C, H, W]
            t (Tensor): [bs], time steps
            clip_denoised (bool): whether to clip predicted X0 to range [-1, 1]
        """
        model_output = model(Xt, t, **model_kwargs)
        # p_variance
        if self.var_type == 'fixed_small':
            model_variance = self._extract(self.posterior_variance, t)
            model_log_variance = self._extract(self.posterior_log_variance, t)
        elif self.var_type == 'fixed_large':
            model_variance = self._extract(self.betas, t)
            model_log_variance = self._extract(torch.log(self.betas), t)
        elif self.var_type == 'learned_range':
            min_log = self._extract(self.posterior_log_variance, t)
            max_log = self._extract(torch.log(self.betas), t)
            model_output, frac = torch.split(model_output, model_output.shape[1] // 2, dim=1)
            frac = (frac + 1) / 2  # [-1, 1] --> [0, 1]
            model_log_variance = frac * max_log + (1 - frac) * min_log
            model_variance = torch.exp(model_log_variance)
        else:
            raise ValueError
        # p_mean
        if self.objective == 'pred_eps':
            pred_eps = model_output
            pred_X0 = self.pred_X0_from_eps(Xt, t, pred_eps)
        elif self.objective == 'pred_x0':
            pred_X0 = model_output
        else:
            raise ValueError
        if clip_denoised:
            pred_X0.clamp_(-1., 1.)
        mean_t, _, _ = self.q_posterior_mean_variance(pred_X0, Xt, t)
        return {'mean': mean_t, 'var': model_variance, 'log_var': model_log_variance, 'pred_X0': pred_X0}

    def p_mean_variance_guided(
            self, p_mean_variance: Dict, Xt: Tensor, t: Tensor,
            cond_fn_eps: Callable = None, cond_fn_X0: Callable = None, cond_fn_mean: Callable = None,
    ):
        """ Apply guidance to p(X{t-1} | Xt)

        Args:
            p_mean_variance (Dict): original mean, variance and pred_X0 of p(X{t-1} | Xt) without guidance
            Xt (Tensor): [bs, C, H, W]
            t (Tensor): [bs], time steps
            cond_fn_eps (Callable): function to apply guidance on predicted eps
            cond_fn_X0 (Callable): function to apply guidance on predicted X0
            cond_fn_mean (Callable): function to apply guidance on mean of p(X{t-1} | Xt)

        Note that at most one of cond_fn_eps, cond_fn_X0 and cond_fn_mean may not be None
        """
        assert sum([cond_fn_eps is not None, cond_fn_X0 is not None, cond_fn_mean is not None]) in [0, 1]
        if cond_fn_eps is not None:
            pred_eps = self.pred_eps_from_X0(Xt, t, p_mean_variance['pred_X0'])
            new_eps = pred_eps + cond_fn_eps(p_mean_variance, Xt, t)
            new_X0 = self.pred_X0_from_eps(Xt, t, new_eps)
            new_mean, _, _ = self.q_posterior_mean_variance(new_X0, Xt, t)
            p_mean_variance.update({'mean': new_mean, 'pred_X0': new_X0})
        if cond_fn_X0 is not None:
            new_X0 = p_mean_variance['pred_X0'] + cond_fn_X0(p_mean_variance, Xt, t)
            new_mean, _, _ = self.q_posterior_mean_variance(new_X0, Xt, t)
            p_mean_variance.update({'mean': new_mean, 'pred_X0': new_X0})
        if cond_fn_mean is not None:
            new_mean = p_mean_variance['mean'] + cond_fn_mean(p_mean_variance, Xt, t)
            # warning: note that pred_X0 is not changed with new_mean
            p_mean_variance.update({'mean': new_mean})
        return p_mean_variance

    def p_sample(
            self, model: nn.Module, Xt: Tensor, t: Tensor, clip_denoised: bool = True,
            cond_fn_eps: Callable = None, cond_fn_X0: Callable = None, cond_fn_mean: Callable = None,
            **model_kwargs,
    ):
        """ Sample from p_theta(X{t-1} | Xt) """
        out = self.p_mean_variance(model, Xt, t, clip_denoised, **model_kwargs)
        out = self.p_mean_variance_guided(out, Xt, t, cond_fn_eps, cond_fn_X0, cond_fn_mean)
        nonzero_mask = torch.ne(t, 0).float().view(-1, 1, 1, 1)
        sample = out['mean'] + nonzero_mask * torch.exp(0.5 * out['log_var']) * torch.randn_like(Xt)
        return {'sample': sample, 'pred_X0': out['pred_X0']}

    def sample_loop(
            self, model: nn.Module, init_noise: Tensor, clip_denoised: bool = True,
            cond_fn_eps: Callable = None, cond_fn_X0: Callable = None, cond_fn_mean: Callable = None,
            **model_kwargs,
    ):
        img = init_noise
        for t in range(self.total_steps-1, -1, -1):
            t_batch = torch.full((img.shape[0], ), t, device=img.device, dtype=torch.long)
            out = self.p_sample(
                model, img, t_batch, clip_denoised,
                cond_fn_eps, cond_fn_X0, cond_fn_mean, **model_kwargs,
            )
            img = out['sample']
            yield out

    def sample(
            self, model: nn.Module, init_noise: Tensor, clip_denoised: bool = True,
            cond_fn_eps: Callable = None, cond_fn_X0: Callable = None, cond_fn_mean: Callable = None,
            **model_kwargs,
    ):
        sample = None
        for out in self.sample_loop(
                model, init_noise, clip_denoised,
                cond_fn_eps, cond_fn_X0, cond_fn_mean, **model_kwargs,
        ):
            sample = out['sample']
        return sample

    def ddim_p_sample(
            self, model: nn.Module, Xt: Tensor, t: Tensor, clip_denoised: bool = True, eta=0.,
            cond_fn_eps: Callable = None, cond_fn_X0: Callable = None, cond_fn_mean: Callable = None,
            **model_kwargs,
    ):
        """ Sample from p_theta(X{t-1} | Xt) using DDIM, similar to p_sample() """
        out = self.p_mean_variance(model, Xt, t, clip_denoised, **model_kwargs)
        out = self.p_mean_variance_guided(out, Xt, t, cond_fn_eps, cond_fn_X0, cond_fn_mean)
        pred_eps = self.pred_eps_from_X0(Xt, t, out['pred_X0'])
        alphas_cumprod_t = self._extract(self.alphas_cumprod, t)
        alphas_cumprod_prev_t = self._extract(self.alphas_cumprod_prev, t)
        var_t = ((eta ** 2) *
                 (1. - alphas_cumprod_prev_t) / (1. - alphas_cumprod_t) *
                 (1. - alphas_cumprod_t / alphas_cumprod_prev_t))
        mean_t = (torch.sqrt(alphas_cumprod_prev_t) * out['pred_X0'] +
                  torch.sqrt(1. - alphas_cumprod_prev_t - var_t) * pred_eps)
        nonzero_mask = torch.ne(t, 0).float().view(-1, 1, 1, 1)
        sample = mean_t + nonzero_mask * torch.sqrt(var_t) * torch.randn_like(Xt)
        return {'sample': sample, 'pred_X0': out['pred_X0']}

    def ddim_sample_loop(
            self, model: nn.Module, init_noise: Tensor, clip_denoised: bool = True, eta: float = 0.,
            cond_fn_eps: Callable = None, cond_fn_X0: Callable = None, cond_fn_mean: Callable = None,
            **model_kwargs,
    ):
        img = init_noise
        for t in range(self.total_steps-1, -1, -1):
            t_batch = torch.full((img.shape[0], ), t, device=img.device, dtype=torch.long)
            out = self.ddim_p_sample(
                model, img, t_batch, clip_denoised, eta,
                cond_fn_eps, cond_fn_X0, cond_fn_mean, **model_kwargs,
            )
            img = out['sample']
            yield out

    def ddim_sample(
            self, model: nn.Module, init_noise: Tensor, clip_denoised: bool = True, eta: float = 0.,
            cond_fn_eps: Callable = None, cond_fn_X0: Callable = None, cond_fn_mean: Callable = None,
            **model_kwargs,
    ):
        sample = None
        for out in self.ddim_sample_loop(
                model, init_noise, clip_denoised, eta,
                cond_fn_eps, cond_fn_X0, cond_fn_mean, **model_kwargs,
        ):
            sample = out['sample']
        return sample


class GuidedSkip(Guided):
    """
    Code adapted from openai:
    https://github.com/openai/improved-diffusion/blob/main/improved_diffusion/respace.py#L63

    A diffusion process which can skip steps in a base diffusion process.
    """
    def __init__(self, timesteps: List[int] or Tensor, **kwargs):
        self.timesteps = timesteps

        # Initialize the original ClassifierFree diffuser
        super().__init__(**kwargs)

        # Define new beta sequence
        betas = []
        last_alphas_cumprod = 1.
        for t in timesteps:
            betas.append(1 - self.alphas_cumprod[t] / last_alphas_cumprod)
            last_alphas_cumprod = self.alphas_cumprod[t]
        betas = torch.tensor(betas)

        # Reinitialize with new betas
        kwargs['betas'] = betas
        super().__init__(**kwargs)

    def p_mean_variance(self, model: nn.Module, *args, **kwargs):
        return super().p_mean_variance(self._wrap_model(model), *args, **kwargs)  # type: ignore

    def _wrap_model(self, model: nn.Module):
        if isinstance(model, _WrappedModel):
            return model
        return _WrappedModel(model, self.timesteps)


class _WrappedModel:
    def __init__(self, model: nn.Module, timesteps: List[int] or Tensor):
        self.model = model
        self.timesteps = timesteps
        if isinstance(timesteps, list):
            self.timesteps = torch.tensor(timesteps)

    def __call__(self, X: Tensor, t: Tensor, **model_kwargs):
        self.timesteps = self.timesteps.to(t.device)
        ts = self.timesteps[t]
        return self.model(X, ts, **model_kwargs)