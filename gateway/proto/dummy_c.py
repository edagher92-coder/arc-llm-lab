from fastmcp import FastMCP
m = FastMCP("c")
@m.tool
def big(n: int = 100000) -> str:
    """Return a long text of n characters (for truncation tests)."""
    return "HEAD-" + "x" * (n - 10) + "-TAIL" if n >= 10 else "x" * n
@m.tool
def small() -> str:
    """Return a short text."""
    return "tiny result"
if __name__ == "__main__": m.run()
