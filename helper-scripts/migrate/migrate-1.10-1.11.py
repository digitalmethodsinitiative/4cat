# all this does is make sure pyppeteer installs chromium
import asyncio
from pyppeteer import launch

print("  Triggering Chromium download...")
async def trigger_chromium_install():
	browser = await launch()
	await browser.close()

asyncio.get_event_loop().run_until_complete(trigger_chromium_install())