# AudioSep context sweep

This is an isolated Stage 5 benchmark experiment. It does not modify the SONORA application or download model weights.

## Run

1. Open [sonora_audiosep_context_sweep.ipynb](./sonora_audiosep_context_sweep.ipynb) in Google Colab.
2. Use a fresh disposable GPU runtime (T4 recommended).
3. Confirm the previously verified AudioSep files exist in Google Drive:
   - `SONORA_Stage5/checkpoints/audiosep/audiosep_base_4M_steps.ckpt`
   - `SONORA_Stage5/checkpoints/audiosep/music_speech_audioset_epoch_15_esc_89.98.pt`
4. Run cells in order. Upload a representative instrument recording when prompted. If no file is selected, the notebook uses a synthetic technical proxy.
5. Review the CSV, plots, direct/chunked WAVs, and JSON summary in `MyDrive/SONORA_Stage5/context_sweep/`.

## Tested comparisons

- Direct inference at 3.5, 5, 7.5 and 13.5 seconds.
- Chunked inference against the 13.5-second direct output, sweeping core sizes 1.5/3/6 seconds and context margins 0.5/1/2/3 seconds.
- Correlation, relative RMS error, output level, boundary-jump telemetry, runtime, and the pinned upstream short-input chunker behavior.

Direct inference is only a self-consistency reference, not clean ground truth. Do not select a production chunking strategy from correlation alone; inspect audio and residuals and consider memory/runtime. The notebook is not a production adapter.
