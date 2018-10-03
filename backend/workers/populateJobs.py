import config

from lib.worker import BasicWorker


class JobPopulator(BasicWorker):
    pause = 10
    max_workers = 1

    def work(self):
        """
        Schedule a board scraping job at the first second of every minute
        :return:
        """
        normalized_time = self.loop_time - (self.loop_time % 60) + 60

        jobs = self.queue.getAllJobs()
        for board in config.boards:
            scheduled = False
            for job in jobs:
                if job["jobtype"] == "board" and job["remote_id"] == board:
                    scheduled = True

            if not scheduled:
                self.log.info("Scheduling board scrape for /%s/" % board)
                self.queue.addJob("board", remote_id=board, claim_after=normalized_time)