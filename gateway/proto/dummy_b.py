from fastmcp import FastMCP
m = FastMCP("b")
@m.tool
def browser_screenshot(url: str) -> str:
    """Take a screenshot of a web page."""
    return f"shot {url}"
@m.tool
def get_current_time(timezone: str = "Australia/Sydney") -> str:
    """Get the current time in a timezone."""
    return "12:00"
if __name__ == "__main__": m.run()
