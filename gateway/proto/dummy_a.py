from fastmcp import FastMCP
m = FastMCP("a")
@m.tool
def read_file(path: str) -> str:
    """Read a text file from disk and return its contents."""
    return f"contents of {path}"
@m.tool
def run_powershell(command: str) -> str:
    """Run a PowerShell command on the PC and return its output."""
    return f"ran {command}"
if __name__ == "__main__": m.run()
