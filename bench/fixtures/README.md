# Test fixtures

`llama-bench-sample.json` is a **format fixture**, not a raw log. It has the structure and field names that `llama-bench -o json` emits (a subset of the fields), filled with the Intel FA values from [data/raw/compare-f16.txt](../../data/raw/compare-f16.txt). The hardware strings in it are placeholders. CI uses it to test that `arc-bench.ps1` and `arc-bench.sh` turn llama-bench output into a valid community result file:

```
bench/arc-bench.sh --from-json bench/fixtures/llama-bench-sample.json --vram-gb 24 --contributor "Example" --driver "example" --out-dir /tmp/out
```
