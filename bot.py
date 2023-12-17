import logging
import re
import tempfile
import urllib.parse
import ujson

import aiohttp
import django.conf
from aiogram import Bot, Dispatcher
from aiogram.types.error_event import ErrorEvent
from aiogram.types.update import Update
from aiovk import TokenSession
from aiovk.drivers import HttpDriver
from aiovk.mixins import LimitRateDriverMixin

import typing as t

from config import *

django.conf.ENVIRONMENT_VARIABLE = SETTINGS_VAR
os.environ.setdefault(SETTINGS_VAR, "settings")
# Ensure settings are read
from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()

from data.models import *


class VkSession(TokenSession):
    API_VERSION = API_VERSION


class RateLimitedDriver(LimitRateDriverMixin, HttpDriver):
    requests_per_period = 1
    period = 0.4


DRIVERS = {}


async def get_driver(vk_token=None):
    if vk_token:
        if vk_token in DRIVERS:
            return DRIVERS[vk_token]
        else:
            new_driver = RateLimitedDriver()
            DRIVERS[vk_token] = new_driver
            return new_driver
    else:
        return RateLimitedDriver()


async def get_vk_chat(cid):
    return VkChat.objects.get_or_create(cid=cid)


def get_max_photo(obj, keyword='photo'):
    maxarr = []
    max_photo_re = re.compile(f'{keyword}_([0-9]*)')
    for k, v in obj.items():
        m = max_photo_re.match(k)
        if m:
            maxarr.append(int(m.group(1)))
    if maxarr:
        return keyword + '_' + str(max(maxarr))


def detect_filename(url: t.Optional[str] = None, out: t.Optional[str] = None, headers: t.Optional[dict] = None,
                    default: t.Optional[str] = "download.wget") -> str:
    """Function was taken from python package "wget" and improved
    Return filename for saving file. If no filename is detected from output
    argument, url or headers, return default (download.wget)
    """
    if out:
        return out
    if url:
        fname = os.path.basename(urllib.parse.urlparse(url).path)
        if fname.strip(" \n\t."):
            return urllib.parse.unquote(fname)
    if headers:
        "https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Content-Disposition"
        if isinstance(headers, str):
            headers = headers.splitlines()
        if isinstance(headers, list):
            headers = dict([x.split(":", maxsplit=1) for x in headers])
        content_disposition = headers.get("Content-Disposition")
        if not content_disposition:
            return default
        if "filename=\"" not in content_disposition:
            return default
        content_disposition = content_disposition.split(";")
        try:
            fname = tuple(filter(lambda x: x.strip().startswith("filename"), content_disposition))[0].split("=")[1].strip("\t")
        except IndexError:
            # Filename not found
            return default
        fname = str(os.path.basename(fname))
        if fname:
            return fname
    return default


async def get_content(url, docname='tgvkbot.document', chrome_headers=True, rewrite_name=False,
                      custom_ext=''):
    try:
        async with aiohttp.ClientSession(headers=CHROME_HEADERS if chrome_headers else {}) as session:
            r = await session.request('GET', url)
            direct_url = str(r.url)
            tempdir = tempfile.gettempdir()
            filename_options = {'out': docname} if rewrite_name else {'default': docname}
            if direct_url != url:
                r.release()
                c = await session.request('GET', direct_url)
                file = detect_filename(direct_url, headers=dict(c.headers), **filename_options)
                temppath = os.path.join(tempdir, file + custom_ext)
                with open(temppath, 'wb') as f:
                    f.write(await c.read())
            else:
                file = detect_filename(direct_url, headers=dict(r.headers), **filename_options)
                temppath = os.path.join(tempdir, file + custom_ext)
                with open(temppath, 'wb') as f:
                    f.write(await r.read())
        content = open(temppath, 'rb')
        return {'content': content, 'file_name': file, 'custom_ext': custom_ext, 'temp_path': tempdir}
    except Exception:
        return {'url': url, 'docname': docname}


bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


@dp.errors()
async def all_errors_handler(error_event: ErrorEvent):
    update: Update = error_event.update
    if 'message' in dir(update) and update.message:
        user = update.message.from_user.full_name
        user_id = update.message.from_user.id
    else:
        user = update.callback_query.from_user.full_name
        user_id = update.callback_query.from_user.id

    logging.exception(f'The update was: {ujson.dumps(update.to_python(), indent=4)}', exc_info=True)

    return True
