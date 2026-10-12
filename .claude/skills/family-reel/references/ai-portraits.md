# Local AI portraits: growing up and ageing together

Optional tier (`doctor.py --install ai`, about 7 GB). Everything runs on CPU with no cloud
calls. Allow about 30 s per 512 px image on 4 cores. With a 3-seed beam, 3 people x 7
ages takes about 30-60 minutes, so run it in the background and report progress.

## Contents
1. Models and licences
2. Identity embeddings
3. The ageing chain
4. Eyes: the failure people notice first
5. Finalise and use in scenes.json
6. What to reject

## 1. Models and licences

The files go in `~/.cache/family-reel/models` (or `$MODELS_DIR`).

| folder | source (Hugging Face) | role |
|---|---|---|
| `pixar-lcm` | `iamanaiart/LCM-disneyPixarCartoon_v10` | SD1.5 + LCM, 3D-animated style, 6-8 steps |
| `faceid` | `h94/IP-Adapter-FaceID` (`ip-adapter-faceid_sd15.bin`) | identity nudge from ArcFace embeddings |
| `buffalo_l` | `immich-app/buffalo_l` | SCRFD face detection + ArcFace recognition (ONNX) |
| `esrgan`, `esrgan_x2` | `Comfy-Org/Real-ESRGAN_repackaged`, `hlky/RealESRGAN_x2plus` | upscaling stills |
| `depth-base` | `depth-anything/Depth-Anything-V2-Base-hf` | depth for parallax (depth tier) |

insightface's pretrained models (buffalo_l, and the FaceID adapter built on them) are for
non-commercial use, and so are the Depth-Anything-V2 Base weights (CC-BY-NC-4.0). That's
fine for a family keepsake, but not for business ads or client work. For business reels,
skip the AI tier and put `depth-anything/Depth-Anything-V2-Small-hf` (Apache-2.0) in the
`depth-base` folder instead. The FaceID LoRA does not map onto this checkpoint; the IP-Adapter alone carries
identity.

## 2. Identity embeddings: `ai/faces.py`

Fill `ai/people.json` with 3-6 clear, front-facing photos per person, and set `pick_x` for
group photos. Run `python ai/faces.py`, then check two things:
- **Pairwise similarity within a person:** above about 0.35. A low one means the wrong face
  was picked.
- **Cross-person similarity:** it should stay low.

Look at `ai/face_refs.jpg`. Never include a goofy, squinting or strongly angled selfie: it
teaches the model a wrong face. Embeddings are biometric data, so keep them out of git and
delete them when done.

## 3. The ageing chain: `ai/chain.py`

Chain img2img from a real face crop instead of using text-to-image. Text-to-image alone
makes figurines and ignores age. A chain keeps composition, so crossfades read as a morph.

- **Source photo:** front-facing, straight gaze, even light. A 3/4 face gives
  sideways-glancing portraits. Set `scale` (crop size around the face) to 1.3-1.9.
- **Strength:** about 0.6 for the first stylised step, 0.55 for children growing up, and
  0.45-0.5 for adults.
- **Prompts:** put the style tag first (CLIP truncates at 77 tokens). Describe hair, eye
  colour, beard or glasses, and "looking straight at the camera, both eyes aligned, soft
  cream background".
- **Teens and adults:** SD1.5 cartoon checkpoints skew young. For 16+ add "adult face,
  slim face" and lower `id` to about 0.35.
- **Adults: anchor, don't chain.** Derive every later age from one good anchor age with
  `"from": "chain/<who>_<anchor>.png"`. Long adult chains drift and accumulate eye errors.
- **Ages:** derive them from the ages the user gives. For example, child 1/3/5/8/12/16/21
  maps to a 33-year-old parent at 34/36/38/41/45/49/54.
- The run is resumable. Delete one output file to regenerate that step.

## 4. Eyes

Cartoon checkpoints drift one eye sideways, and it is the first thing a parent sees.

1. **Negative prompt:** `cfg` 1.5 with the negative prompt built in (cross-eyed, lazy eye,
   looking sideways, and so on).
2. **Seed beam:** `"beam": [7, 11, 23]` tries seeds per step. `ai/eyeqa.py` scores the iris
   offsets (lower is better, above about 0.08 is flagged), and the best one wins. Every
   candidate is kept in `ai/beam/`.
3. **Eye transplant:** for adult ages from an anchor,
   `python ai/eyetransplant.py ai/chain/dad_38.png ai/chain/dad_45.png ... --replace` copies the
   anchor's aligned eyes onto each older face, colour-matched and feathered.
4. **Look.** `python ai/sheet.py`, then open every face at full size. The metric misses
   subtle cases. Mirroring one eye was tried and rejected: it leaves a visible seam.

## 5. Finalise and use

`python ai/finalize.py` writes `assets/age/<who>_<tag>.jpg` (600 px) and
`assets/age/<who>_today.jpg`, inpainting the small magenta blemishes the IP-Adapter
sometimes leaves on foreheads. Photos declared as `{"chain": "child_21"}` in
`scenes.json` become Real-ESRGAN x4 full-screen stills for milestone shots. Reference the
portraits from `ageing.steps`. If the gown or background shows an artefact, hide it with
the ring's `zoom`/`lift`.

## 6. What to reject

- Multi-person AI scenes (`ai/gen.py`) lose likeness. Show milestones on single portraits
  with captions, or use the frozen "someday" reunion layout.
- AI-aged pets look uncanny. Key a sprite from the user's own clip of the pet instead.
- Any face you would not show the family. Regenerate, change the source photo, or drop that
  age.
