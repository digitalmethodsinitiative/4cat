import requests
import random
import base64
import time

from lib.worker import BasicWorker
import config


class ImageDownloader(BasicWorker):
    pause = 1
    max_workers = 3

    def work(self):
        job = self.queue.getJob("image")
        if not job:
            self.log.debug("Image downloader has no jobs, sleeping for 10 seconds")
            time.sleep(10)
            return

        try:
            url = "http://i.4cdn.org/%s/%s%s" % (job["details"]["board"], job["details"]["tim"], job["details"]["ext"])
            image = requests.get(url)
        except requests.HTTPError:
            # something wrong with our internet connection? or blocked by 4chan?
            # try again in a minute
            self.queue.releaseJob(job, delay=60)
            return

        if image.status_code == 404:
            # image deleted - mark in database? either way, can't complete job
            self.queue.finishJob(job)
            return
        elif image.status_code != 200:
            # try again in 30 seconds
            if job["attempts"] > 2:
                self.log.warning("Could not download image %s after x retries (last response code %s), aborting", (url, image.status_code))
                self.queue.finishJob(job)
            else:
                self.log.info("Got response code %s while trying to download image %s, retrying later" % (image.status_code, url))
                self.queue.releaseJob(job, delay=random.choice(range(5, 35)))

            return

        # write image to disk
        image_location = job["details"]["destination"]
        with open(image_location, 'wb') as f:
            for chunk in image.iter_content(1024):
                f.write(chunk)

        # done!
        self.queue.finishJob(job)
