# GPU comparison: method and sources

- **Specs** (VRAM, memory bandwidth) are vendor specifications as listed in the TechPowerUp GPU database: https://www.techpowerup.com/gpu-specs/
- **Prices** are Australian street prices from the linked trackers on the given dates. Blank means no reliable AUD source was found, so none is shown rather than guessed.
- **Fits 27B Q4 + 32K context:** Qwen3.8-27B UD-Q4_K_M weights 16.46 GB, plus the DFlash2 drafter and buffers (17.15 GiB measured), plus 2.0 GiB f16 KV for 32K, plus at least 1.1 GiB headroom, comes to about 21 GB of VRAM.
- **Theoretical decode ceiling = memory bandwidth / 16.46 GB.** Without speculative decoding, a dense model must stream every weight once per generated token, so this is an upper bound that real systems reach 50-80% of. It is an estimate, not a measurement, for every card except the B60.
- **B60 measured:** 16.0 tok/s without a drafter (58% of its ceiling, data/raw/compare-f16.txt); 42.3 tok/s with the DFlash2 drafter (data/raw/tune.txt). Speculative decoding verifies several drafted tokens per pass over the weights, which is how it exceeds the no-drafter ceiling. Other cards would gain from it too.
