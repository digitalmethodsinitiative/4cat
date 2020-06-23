"""
Instagram-specific web tool call hooks
"""
import re

import instaloader

def authenticate(request, user, **kwargs):
	"""
	Check authentication with provided API credentials

	Tries to connect to the Instagram API to verify login

	:param request:  The Flask request through which this was called
	:param user:  The user object for the user making the request
	:param kwargs:  Parameters
	:return:  Result data
	"""
	if not user or not user.is_authenticated or user.is_anonymous:
		return {"error": "auth",
				"error-message": "Instagram scraping is only available to logged-in users with personal accounts."}

	# check for the information we need
	if "username" not in kwargs or "password" not in kwargs:
		return False

	kwargs = {key: kwargs[key][0].strip() for key in kwargs}

	instagram = instaloader.Instaloader()
	try:
		instagram.login(kwargs["username"], kwargs["password"])
	except instaloader.TwoFactorAuthRequiredException:
		return {"error": "2fa", "error-message": "Two-factor authentication with Instagram is not available via 4CAT at this time. Disable it for your Instagram account and try again."}
	except (instaloader.BadCredentialsException, instaloader.InvalidArgumentException):
		return {"error": "credentials", "error-message": "Invalid username or password"}
	except instaloader.ConnectionException as e:
		if "Checkpoint required" in str(e):
			link = re.search(r"(https://[^\s]+)", str(e))[1]
			return {"checkpoint-link": link}
		else:
			return {"error": "other", "error-message": "Could not succesfully connect to Instagram"}

	return {"authenticated": True}
