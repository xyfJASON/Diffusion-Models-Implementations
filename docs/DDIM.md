# DDIM

> Song, Jiaming, Chenlin Meng, and Stefano Ermon. "Denoising Diffusion Implicit Models." In *International Conference on Learning Representations*. 2020.



## Sampling

This repo uses the [🤗 Accelerate](https://huggingface.co/docs/accelerate/index) library for multi-GPUs/fp16 supports. Please read the [documentation](https://huggingface.co/docs/accelerate/basic_tutorials/launch#using-accelerate-launch) on how to launch the script on different platforms.

```shell
accelerate-launch scripts/sample_uncond.py -c CONFIG \
                                           --weights WEIGHTS \
                                           --sampler ddim \
                                           --ddim_eta DDIM_ETA \
                                           --n_samples N_SAMPLES \
                                           --save_dir SAVE_DIR \
                                           [--seed SEED] \
                                           [--batch_size BATCH_SIZE] \
                                           [--respace_type RESPACE_TYPE] \
                                           [--respace_steps RESPACE_STEPS] \
                                           [--mode {sample,interpolate,reconstruction}] \
                                           [--n_interpolate N_INTERPOLATE] \
                                           [--input_dir INPUT_DIR]
```

Basic arguments:

- `-c CONFIG`: path to the inference configuration file.
- `--weights WEIGHTS`: path to the model weights (checkpoint) file.
- `--sampler ddim`: set the sampler to DDIM.
- `--n_samples N_SAMPLES`: number of samples.
- `--save_dir SAVE_DIR`: path to the directory where samples will be saved.
- `--mode MODE`: choose a sampling mode, the options are:
  - "sample" (default): randomly sample images
  - "interpolate": sample two random images and interpolate between them. Use `--n_interpolate` to specify the number of images in between.
  - "reconstruction":  encode a real image from dataset with **DDIM inversion** (DDIM encoding), and then decode it with DDIM sampling.

Advanced arguments:

- `--ddim_eta`: parameter eta in DDIM sampling.
- `--respace_steps RESPACE_STEPS`: faster sampling that uses respaced timesteps.
- `--batch_size BATCH_SIZE`: Batch size on each process. Sample by batch is faster, so set it as large as possible to fully utilize your devices.

See more details by running `python sample_ddim.py -h`.

For example, to sample 50000 images from a pretrained CIFAR-10 model with 100 DDIM steps:

```shell
accelerate-launch scripts/sample_uncond.py -c ./configs/ddpm_cifar10.yaml --weights /path/to/model/weights --sampler ddim --n_samples 50000 --save_dir ./samples/ddim-cifar10 --respace_steps 100
```



## Evaluation

Sample 10K-50K images following the previous section and evaluate image quality with tools like [torch-fidelity](https://github.com/toshas/torch-fidelity), [pytorch-fid](https://github.com/mseitzer/pytorch-fid), [clean-fid](https://github.com/GaParmar/clean-fid), etc.



## Results

**FID and IS on CIFAR-10 32x32**:

All the metrics are evaluated on 50K samples using [torch-fidelity](https://torch-fidelity.readthedocs.io/en/latest/index.html) library.

<table align="center" width=100%>
  <tr>
    <th align="center">eta</th>
    <th align="center">timesteps</th>
    <th align="center">FID ↓</th>
    <th align="center">IS ↑</th>
  </tr>
  <tr>
    <td align="center" rowspan="5">0.0</td>
    <td align="center">1000</td>
    <td align="center">4.1892</td>
    <td align="center">9.0626 ± 0.1093</td>
  </tr>
  <tr>
    <td align="center">100 (10x faster)</td>
    <td align="center">6.0508</td>
    <td align="center">8.8424 ± 0.0862</td>
  </tr>
  <tr>
    <td align="center">50 (20x faster)</td>
    <td align="center">7.7011</td>
    <td align="center">8.7076 ± 0.1021</td>
  </tr>
  <tr>
    <td align="center">20 (50x faster)</td>
    <td align="center">11.6506</td>
    <td align="center">8.4744 ± 0.0879</td>
  </tr>
  <tr>
    <td align="center">10 (100x faster)</td>
    <td align="center">18.9559</td>
    <td align="center">8.0852 ± 0.1137</td>
  </tr>
 </table>



**Sample with fewer steps**:

<p align="center">
  <img src="../assets/ddim-cifar10.png" width=50% />
</p>

From top to bottom: 10 steps, 50 steps, 100 steps and 1000 steps. It can be seen that fewer steps leads to blurrier results, but human eyes can hardly distinguish the difference between 50/100 steps and 1000 steps.



**Spherical linear interpolation (slerp) between two samples (sample with 100 steps)**:

<p align="center">
  <img src="../assets/ddim-cifar10-interpolate.png" width=60% />
</p>

<p align="center">
  <img src="../assets/ddim-celebahq-interpolate.png" width=60% />
</p>


**Reconstruction (sample with 100 steps)**:

<p align="center">
  <img src="../assets/ddim-cifar10-reconstruction.png" width=60% />
</p>

In each pair, image on the left is the real image sampled from dataset, the other is the reconstructed image generated by DDIM inversion + DDIM sampling.



**Reconstruction (sample with 1000 steps)**:

<p align="center">
  <img src="../assets/ddim-celebahq-reconstruction.png" width=60% />
</p>
