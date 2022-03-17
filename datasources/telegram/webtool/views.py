"""
Telegram-specific web tool call hooks
"""
import traceback
import hashlib
import asyncio

from pathlib import Path

from telethon.sync import TelegramClient
from telethon.errors.rpcerrorlist import FloodWaitError, ApiIdInvalidError, PhoneNumberInvalidError

from datasources.telegram.search_telegram import SearchTelegram

import config

def authenticate(request, user, **kwargs):
	"""
	Check authentication with provided API credentials

	Tries to connect to the Telegram API and if needed send a Telegram message
	with confirmation code.

	:param request:  The Flask request through which this was called
	:param user:  The user object for the user making the request
	:param kwargs:  Parameters
	:return:  Result data
	"""
	if not user or not user.is_authenticated or user.is_anonymous:
		return {"error": "auth",
				"error-message": "Telegram scraping is only available to logged-in users with personal accounts."}

	# check for the information we need
	if "api_phone" not in kwargs or "api_id" not in kwargs or "api_hash" not in kwargs:
		return False

	kwargs = {key: kwargs[key].strip() for key in kwargs}

	# session IDs need to be unique...
	# Sessions are important because they are the way we don't need to enter
	# the security code all the time. If we've tried logging in earlier use
	# the same session again.
	session_id = SearchTelegram.create_session_id(kwargs["api_phone"], kwargs["api_id"], kwargs["api_hash"])

	# store session ID for user so it can be found again for later queries
	user.set_value("telegram.session", session_id)
	session_path = Path(config.PATH_ROOT).joinpath(config.PATH_SESSIONS, session_id + ".session")


	client = None

	# API ID is always a number, if it's not, we can immediately fail
	try:
		api_id = int(kwargs["api_id"])
	except ValueError:
		return {"error": "other", "error-message": "Invalid API ID."}

	# maybe we've entered a code already and submitted it with the request
	if "code" in kwargs and kwargs["code"].strip():
		code_callback = lambda: kwargs["code"]
		max_attempts = 1
	else:
		code_callback = lambda: -1
		# max_attempts = 0 because authing will always fail: we can't wait for
		# the code to be entered interactively, we'll need to do a new request
		# but we can't just immediately return, we still need to call start()
		# to get telegram to send us a code
		max_attempts = 0

	# now try autenticating
	try:
		loop = asyncio.new_event_loop()
		asyncio.set_event_loop(loop)
		client = TelegramClient(str(session_path), api_id, kwargs["api_hash"], loop=loop)

		try:
			client.start(max_attempts=max_attempts, phone=kwargs.get("api_phone"), code_callback=code_callback)
			result = {"authenticated": True, "session": session_id}

		except ValueError as e:
			# this happens if 2FA is required
			result = {"error": "2fa",
					  "error-message": "Your account requires two-factor authentication. 4CAT at this time does not support this authentication mode for Telegram. (%s)" % e}
		except RuntimeError:
			# A code was sent to the given phone number
			result = {"authenticated": False, "session": session_id}
	except FloodWaitError as e:
		# uh oh, we got rate-limited
		result = {"error": "rate-limit",
				  "error-message": "You were rate-limited and should wait a while before trying again. " +
								   str(e).split("(")[0] + ".", "authenticated": False}
	except ApiIdInvalidError as e:
		# wrong credentials
		result = {"error": "auth", "error-message": "Your API credentials are invalid."}
	except PhoneNumberInvalidError as e:
		# wrong phone number
		result = {"error": "auth",
				  "error-message": "The phone number provided is not a valid phone number for these credentials."}
	except Exception as e:
		# ?
		result = {"error": "other",
				  "error-message": "An unexpected error (%s) occurred and your authentication could not be verified." % e,
				  "error-trace": traceback.format_exc()}
		pass
	finally:
		if client:
			client.disconnect()

	return result
