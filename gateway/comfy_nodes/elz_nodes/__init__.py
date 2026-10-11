"""Elz nodes: small guards for the Intel XPU video pipeline. Copy this folder into ComfyUI/custom_nodes/ and whitelist it (--whitelist-custom-nodes elz_nodes)."""
import torch


class AudioNanGuard:
    """Replace NaN/Inf samples in a decoded audio clip with silence so the AAC muxer never rejects the file; logs how much was bad."""
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {"audio": ("AUDIO",)}}
    RETURN_TYPES = ("AUDIO",)
    FUNCTION = "run"
    CATEGORY = "elz"

    def run(self, audio):
        w = audio["waveform"]
        bad = int((~torch.isfinite(w)).sum().item())
        print("ELZ_AUDIO_GUARD samples=%d nonfinite=%d (%.1f%%) absmax=%.4f" % (w.numel(), bad, 100.0 * bad / max(1, w.numel()), float(torch.nan_to_num(w, nan=0.0, posinf=0.0, neginf=0.0).abs().max())), flush=True)
        if bad:
            w = torch.nan_to_num(w, nan=0.0, posinf=0.0, neginf=0.0).clamp(-1.0, 1.0)
        return ({"waveform": w, "sample_rate": audio["sample_rate"]},)


NODE_CLASS_MAPPINGS = {"ElzAudioNanGuard": AudioNanGuard}
NODE_DISPLAY_NAME_MAPPINGS = {"ElzAudioNanGuard": "Audio NaN guard (Elz)"}
