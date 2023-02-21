# DDIM

> Song, Jiaming, Chenlin Meng, and Stefano Ermon. "Denoising Diffusion Implicit Models." In *International Conference on Learning Representations*. 2020.



## Training

DDIM shares the same training process with DDPM. Please refer to [DDPM doc](./DDPM.md).



## Sampling

```shell
python sample_ddim.py --config_data CONFIG_DATA \
                      --config_model CONFIG_MODEL \
                      --config_diffusion CONFIG_DIFFUSION \
                      [--seed SEED] \
                      --weights WEIGHTS \
                      [--load_ema LOAD_EMA] \
                      [--ddim_eta DDIM_ETA] \
                      [--skip_type {uniform,quad}] \
                      [--skip_steps SKIP_STEPS] \
                      --n_samples N_SAMPLES \
                      --save_dir SAVE_DIR \
                      [--batch_size BATCH_SIZE] \
                      [--mode {sample,interpolate,reconstruction}] \
                      [--n_interpolate N_INTERPOLATE] \
                      [--data_*** ***] \
                      [--model_*** ***] \
                      [--diffusion_*** ***]
```

- To sample on multiple GPUs, replace `python` with `torchrun --nproc_per_node NUM_GPUS`.
- Use `--skip_steps SKIP_STEPS` for faster sampling that skip timesteps.
- Choose a sampling mode by `--mode MODE`, the options are:
  - `sample` (default): randomly sample images
  - `interpolate`: sample two random images and interpolate between them. Use `--n_interpolate` to specify the number of images in between.
  - `reconstruction`:  encode a real image from dataset with **DDIM inversion**, and then decode it with DDIM sampling.
- Specify `--batch_size BATCH_SIZE` to sample images batch by batch. Set it as large as possible to fully utilize your devices. The default value of 1 is pretty slow.



## Evaluation

Same as DDPM. Please refer to [DDPM doc](./DDPM.md).



## Results

**FID and IS on CIFAR-10 32x32**:

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



**Sample with fewer steps**:

<p align="center">
  <img src="../assets/ddim-cifar10.png" width=50% />
</p>

From top to bottom: 10 steps, 50 steps, 100 steps and 1000 steps. It can be seen that fewer steps leads to blurrier results.



**Spherical linear interpolation (slerp) between two samples (100 steps)**:

<p align="center">
  <img src="../assets/ddim-cifar10-interpolate.png" width=60% />
</p>

<p align="center">
  <img src="../assets/ddim-celebahq-interpolate.png" width=60% />
</p>



**Reconstruction (100 steps)**:

<p align="center">
  <img src="../assets/ddim-cifar10-reconstruction.png" width=60% />
</p>


In each pair, image on the left is the real image sampled from dataset, the other is the reconstructed image generated by DDIM inversion + DDIM sampling.



**Reconstruction (1000 steps)**:

<p align="center">
  <img src="../assets/ddim-celebahq-reconstruction.png" width=60% />
</p>
