# Diffusion-Models-Implementations

My implementations of Diffusion Models with PyTorch.



## Progress

- [x] DDPM
- [x] DDIM
- [ ] Classifier Guidance
- [x] Classifier-Free Guidance

<br/>

## Sampling Algorithms: Fidelity-Speed Visualization

I use the same model in all tests, which is trained following the standard DDPM. Thus the comparison depends only on the performance of different sampling algorithms (or SDE/ODE solvers).

<p align="center">
  <img src="./assets/fidelity-speed-visualization.png" width=80% />
</p>

Interesting facts observed:

- DDPM (fixed-large) performs better than DDPM (fixed-small) with 1000 steps, but degrades drastically as the number of steps decreases. If you check on the samples from DDPM (fixed-large) (<= 100 steps), you'll find that they still contain noticeable noises.
- DDPM (fixed-small) and DDIM (eta=1) are theoretically the same, and indeed, their curves are very close, especially in the FID case.

<br/>

## DDPM [[doc](./docs/DDPM.md)] [[official repo](https://github.com/hojonathanho/diffusion)]

**Quantitative results on CIFAR-10 32x32**:

<table align="center" width=100%>
  <tr>
    <th align="center">Type of variance</th>
    <th align="center">timesteps</th>
    <th align="center">FID ↓</th>
    <th align="center">IS ↑</th>
  </tr>
  <tr>
    <td align="center" rowspan="4">fixed-large</td>
    <td align="center">1000</td>
    <td align="center"><b>3.1246</b></td>
    <td align="center"><b>9.3690 (0.1015)</b></td>
  </tr>
  <tr>
    <td align="center">100 (10x faster)</td>
    <td align="center">45.7398</td>
    <td align="center">8.6780 (0.1260)</td>
  </tr>
  <tr>
    <td align="center">50 (20x faster)</td>
    <td align="center">85.2383</td>
    <td align="center">6.2571 (0.0939)</td>
  </tr>
  <tr>
    <td align="center">10 (100x faster)</td>
    <td align="center">267.5894</td>
    <td align="center">1.5900 (0.0082)</td>
  </tr>
  <tr>
    <td align="center" rowspan="4">fixed-small</td>
    <td align="center">1000</td>
    <td align="center">5.3026</td>
    <td align="center">8.9711 (0.1172)</td>
  </tr>
  <tr>
    <td align="center">100 (10x faster)</td>
    <td align="center">11.1331</td>
    <td align="center">8.5436 (0.1291)</td>
  </tr>
  <tr>
    <td align="center">50 (20x faster)</td>
    <td align="center">15.5682</td>
    <td align="center">8.3658 (0.0665)</td>
  </tr>
  <tr>
    <td align="center">10 (100x faster)</td>
    <td align="center">40.8977</td>
    <td align="center"> 7.1148 (0.0824)</td>
  </tr>
 </table>




**Qualitative results**:

<table align="center" width=100%>
  <tr>
    <th align="center" width=10%>Dataset</th>
    <th align="center" width=16%>Random samples</th>
    <th align="center" width=37%>Denoising process</th>
    <th align="center" width=37%>Progressive generation</th>
  </tr>
  <tr>
    <th align="center">MNIST<br/>32x32</th>
    <td align="center"><img src="./assets/ddpm-mnist-random.png"/></td>
    <td align="center"><img src="./assets/ddpm-mnist-denoise.png"/></td>
    <td align="center"><img src="./assets/ddpm-mnist-progressive.png"/></td>
  </tr>
  <tr>
    <th align="center">CIFAR-10<br/>32x32</th>
    <td align="center"><img src="./assets/ddpm-cifar10-random.png"/></td>
    <td align="center"><img src="./assets/ddpm-cifar10-denoise.png"/></td>
    <td align="center"><img src="./assets/ddpm-cifar10-progressive.png"/></td>
  </tr>
  <tr>
    <th align="center">CelebA-HQ<br/>256x256</th>
    <td align="center"><img src="./assets/ddpm-celebahq-random.png"/></td>
    <td align="center"><img src="./assets/ddpm-celebahq-denoise.png"/></td>
    <td align="center"><img src="./assets/ddpm-celebahq-progressive.png"/></td>
  </tr>
 </table>


:warning: Results on CelebA-HQ 256x256 suffer from severe color shifting problem, and I currently have no clue about it.

<br/>

## DDIM [[doc](./docs/DDIM.md)] [[official repo](https://github.com/ermongroup/ddim)]

**Quantitative results on CIFAR-10 32x32**:

<table align="center" width=100%>
  <tr>
    <th align="center">eta</th>
    <th align="center">timesteps</th>
    <th align="center">FID ↓</th>
    <th align="center">IS ↑</th>
  </tr>
  <tr>
    <td align="center" rowspan="4">0.0</td>
    <td align="center">1000</td>
    <td align="center">4.2221</td>
    <td align="center">9.0388 (0.0994)</td>
  </tr>
  <tr>
    <td align="center">100 (10x faster)</td>
    <td align="center">6.0774</td>
    <td align="center">8.7873 (0.1186)</td>
  </tr>
  <tr>
    <td align="center">50 (20x faster)</td>
    <td align="center">7.7867</td>
    <td align="center">8.6770 (0.1304)</td>
  </tr>
  <tr>
    <td align="center">10 (100x faster)</td>
    <td align="center">18.9220</td>
    <td align="center">8.0326 (0.0961)</td>
  </tr>
  <tr>
    <td align="center" rowspan="4">1.0</td>
    <td align="center">1000</td>
    <td align="center">5.2496</td>
    <td align="center">8.8996 (0.1010)</td>
  </tr>
  <tr>
    <td align="center">100 (10x faster)</td>
    <td align="center">11.1593</td>
    <td align="center">8.5983 (0.1114)</td>
  </tr>
  <tr>
    <td align="center">50 (20x faster)</td>
    <td align="center">15.2403</td>
    <td align="center">8.3222 (0.1139)</td>
  </tr>
  <tr>
    <td align="center">10 (100x faster)</td>
    <td align="center">40.6563</td>
    <td align="center">7.1315 (0.0682)</td>
  </tr>
 </table>



**Qualitative results**:

- Sample with fewer steps:

  <p align="center">
    <img src="./assets/ddim-cifar10.png" width=50% />
  </p>

  From top to bottom: 10 steps, 50 steps, 100 steps and 1000 steps. It can be seen that fewer steps leads to blurrier results.

- Spherical linear interpolation (slerp) between two samples (100 steps):

  <p align="center">
    <img src="./assets/ddim-cifar10-interpolate.png" width=60% />
  </p>
  
  <p align="center">
    <img src="./assets/ddim-celebahq-interpolate.png" width=60% />
  </p>

<br/>

## Classifier-Free Guidance [[doc](./docs/Classifier-Free Guidance.md)]

:small_orange_diamond: I use $s$ in [Classifier Guidance paper](https://arxiv.org/abs/2105.05233) as the scale factor rather than $w$ in the [Classifier-Free Guidance paper](https://arxiv.org/abs/2207.12598). In fact, we have $s=w+1$, and:

- $s=0$: unconditional generation
- $s=1$: non-guided conditional generation
- $s>1$: guided conditional generation



**Quantitative results on CIFAR-10 32x32**:

Note: The images for evaluation are sampled using DDIM with 50 steps.

<table align="center" width=100%>
  <tr>
    <th align="center">guidance scale</th>
    <th align="center">FID ↓</th>
    <th align="center">IS ↑</th>
  </tr>
  <tr>
    <td align="center">0 (unconditional)</td>
    <td align="center">6.1983</td>
    <td align="center">8.9323 (0.1542)</td>
  </tr>
  <tr>
    <td align="center">1 (non-guided conditional)</td>
    <td align="center">4.6546</td>
    <td align="center">9.2524 (0.1606)</td>
  </tr>
  <tr>
    <td align="center">3 (unconditional)</td>
    <td align="center">9.9375</td>
    <td align="center">9.5522 (0.1013)</td>
  </tr>
  <tr>
    <td align="center">5 (unconditional)</td>
    <td align="center">13.3187</td>
    <td align="center">9.4688 (0.1588)</td>
  </tr>
</table>

FID measures diversity and IS measures fidelity. This table shows diversity-fidelity trade-off as guidance scale increases.




**Qualitative results**:

<p align="center">
  <img src="./assets/classifier-free-cifar10.png" />
</p>

From left to right: $s=0$ (unconditional), $s=1.0$ (non-guided conditional), $s=3.0$, $s=5.0$. Each row corresponds to a class.

