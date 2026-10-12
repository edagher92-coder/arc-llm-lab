"""Stand-alone MCP server that exposes only ask_local, so Claude Code can hand coding subtasks to the local Qwen.

Usage (registered once, user scope):  claude mcp add qwen --scope user -- <gateway python> qwen_mcp.py [gateway.json]
Reads the same gateway.json "video.llm" block as the hub; checks the governor mode file and the hub's state/video/gpu.lock
(GW_STATE_DIR, default <here>/state) so a running render is never interrupted. Docs: docs/LOCAL-LLM.md.
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from fastmcp import FastMCP
import tools_local_llm


def build(cfg_path=None):
    cfg = json.load(open(cfg_path or os.path.join(HERE, "gateway.json"), encoding="utf-8-sig"))
    state = os.environ.get("GW_STATE_DIR") or os.path.join(HERE, "state")
    mcp = FastMCP("qwen")
    tools_local_llm.register(mcp, None, HERE, cfg, gpu_lock=os.path.join(state, "video", "gpu.lock"))
    return mcp


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else None).run()
