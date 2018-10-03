import requests
import time

from lib.worker import BasicWorker
import config


class ImageDownloader(BasicWorker):
    pause = 1
    max_workers = 3

    def work(self):
        job = self.queue.getJob("image")
        if not job:
            self.log.info("Image downloader has no jobs, sleeping for 10 seconds")
            time.sleep(10)
            return

        self.queue.finishJob(job)
        return

        # todo
        try:
            url = "http://i.4cdn.org/%s/%s%s" % (job["board"], job["tim"], job["ext"])
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
            self.queue.releaseJob(job, delay=30)
            self.log.warning("Got response code %s while trying to download image %s" % (image.status_code, url))
            return

        # write image to disk
        image_location = config.image_path + "/" + job["md5"] + job["ext"]
        with open(image_location, 'wb') as f:
            for chunk in image.iter_content(1024):
                f.write(chunk)

        # done!
        self.queue.finishJob(job)
