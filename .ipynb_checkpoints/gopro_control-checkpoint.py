import time
from open_gopro import WiredGoPro, Params
import os
import requests
import numpy as np
import datetime
from datetime import timezone
from astral.sun import sun
from astral import LocationInfo
import pytz
import json
import re
import signal
import subprocess
from PIL import Image
from PIL import ImageFont
from PIL import ImageDraw
import os
import netifaces as ni

#serial number of GoPro
sn='C3471325923859'
ip='172.28.159.51'

font = ImageFont.truetype("/usr/share/fonts/truetype/freefont/FreeSans.ttf", 72)
fontsmall = ImageFont.truetype("/usr/share/fonts/truetype/freefont/FreeSans.ttf", 36)
fontcolor = (238,161,6)

def utc_to_local(utc_dt):
    return utc_dt.replace(tzinfo=timezone.utc).astimezone(tz=None)

def is_dst(dt=None, timezone='CET'):
    """Is daylight savings in effect?"""
    if dt is None:
        dt = datetime.datetime.utcnow()
    timezone = pytz.timezone(timezone)
    timezone_aware_date = timezone.localize(dt, is_dst=None)
    return timezone_aware_date.tzinfo._dst.seconds != 0

def sunrise_sunset(date):
    """Get the sunrise and sunset times adjusted for DST."""
    # 'date' is taken at midnight, but daylight savings starts/ends at 1am/2am
    # so move the time to midday to be accurate
    #tdelta = datetime.timedelta(hours=12)
    #date = date + tdelta
    # Get the unadjusted sunrise and sunset times
    city = LocationInfo(
        'Locarno', 'Switzerland', 'Europe/London', 46.17123, 8.79050
    )
    s = sun(city.observer, date=date)
    sunrise = s['sunrise']
    sunset = s['sunset']
    # Initialise a time zone
    timezone = 'CET'
    # Is daylight savings in effect?
    if is_dst(date, timezone='Europe/London'):
        tdelta = datetime.timedelta(hours=1)
        sunrise = sunrise - tdelta
        sunset = sunset + tdelta
        timezone = 'CET'
    # To be conservative, round the time up to the nearest minute
    if sunrise.second > 0:
        sunrise = sunrise + datetime.timedelta(minutes=1)
    if sunrise.second > 13:
        sunset = sunset + datetime.timedelta(minutes=1)
    return utc_to_local(sunrise), utc_to_local(sunset)

class SignalHandler:
    shutdown_requested = False

    def __init__(self):
        signal.signal(signal.SIGINT, self.request_shutdown)
        signal.signal(signal.SIGTERM, self.request_shutdown)

    def request_shutdown(self, *args):
        print('Request to shutdown received, stopping')
        self.shutdown_requested = True

    def can_run(self):
        return not self.shutdown_requested


signal_handler = SignalHandler()

while signal_handler.can_run():
    basepath = '/home/pi/autofs/data/gopro/'
    date = datetime.datetime.now()
    sunrise, sunset = sunrise_sunset(date)
    sunrise = sunrise.replace(tzinfo=None)
    sunset = sunset.replace(tzinfo=None)

    if sunrise <= date <= sunset:
        saveday = date.strftime('%Y%m%d')
        #print('Start capturing daytime photos.')
        try:
            #serial='C3471325923859'
            with WiredGoPro(serial=sn) as gopro:
                gopro.http_command.wired_usb_control(control=Params.Toggle.ENABLE)
                gopro.http_command.set_keep_alive()
                gopro.http_command.load_preset_group(group=Params.PresetGroup.PHOTO)
                gopro.http_setting.max_lens_mode.set(Params.MaxLensMode(1))
                gopro.http_setting.photo_horizon_leveling.set(Params.HorizonLeveling(2))
                gopro.http_setting.photo_field_of_view.set(Params.PhotoFOV(101))
                gopro.http_setting.auto_off.set(Params.AutoOff(0)) #Never do auto off the camera
                #Take photo
                gopro.http_command.set_shutter(Params.ExposureMode.AUTO, Params.Flatmode.SINGLE_PHOTO, shutter=Params.Toggle.ENABLE)

                # Download and delete all of the files from the camera
                media_list = [x["n"] for x in gopro.http_command.get_media_list().flatten]
                for f in media_list:
                    #print('Download ', f)
                    epoch_file = gopro.http_command.get_media_info(file=f).data['cre']
                    utc_file = datetime.datetime.fromtimestamp(int(epoch_file))
                    tstr = utc_file.strftime('%Y%m%d-%H%M%S')
                    lpath = basepath+'day/'+tstr[0:8]+'/'
                    if not os.path.exists(lpath):
                        os.makedirs(lpath)
                    lfile = lpath+tstr+'.JPG'
                    gopro.http_command.download_file(camera_file=f, local_file=lfile)
                    filename=tstr+'.JPG'
                    splitup = filename.split("-")
                    date = splitup[0]
                    t = splitup[1][0:4]
                    tformatted = t[0:2] + ":" + t[2:4]
                    img = Image.open(lfile)
                    draw = ImageDraw.Draw(img)
                    draw.text((img.width-220,img.height-150), date, fontcolor, font=fontsmall)
                    draw.text((img.width-220,img.height-120), tformatted, fontcolor, font=font)
                    img.save(lfile)

                    #print('Delete ', f)
                    url = "http://"+ip+":8080/gp/gpControl/command/storage/delete?p=" + "/100GOPRO/" + f
                    with requests.get(url) as request:
                        request.raise_for_status()

            time.sleep(7) #Processing break

        except:
            time.sleep(3)
            pass

    else:
        lpath = basepath+'day/'+saveday+'/'
        #During night process timelapse if not exist after sunset
        if os.path.isfile(basepath+'timelapse/timelapse_'+saveday+'.mp4'):
            time.sleep(10)
        else:
            #Timelapse generation
            command = "ffmpeg -framerate 16 -pattern_type glob -i '"+lpath+'*.JPG'+"' -s:v 3504x2624 -c:v libx264 -crf 17 -pix_fmt yuv420p "+basepath+"timelapse/timelapse_"+saveday+".mp4"
            subprocess.call(command,shell=True)

        #print("Sleeping")
        try:
            with WiredGoPro(serial=sn) as gopro:
                gopro.http_command.wired_usb_control(control=Params.Toggle.ENABLE)
                gopro.http_command.set_keep_alive()
                gopro.http_setting.auto_off.set(Params.AutoOff(0)) #Never do auto off the camera
                
                time.sleep(30)
        except:
            time.sleep(30)
            pass
