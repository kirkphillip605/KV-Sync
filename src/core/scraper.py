# src/core/scraper.py
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from bs4 import BeautifulSoup
from src.core.date_utils import intelligent_date_parse

logger = logging.getLogger('vibe_manager')  # Use the main logger


class SongScraper:

    def __init__(self, base_url, username, password, session):
        self.base_url = base_url
        self.username = username
        self.password = password
        self.session = session

    def login(self):
        """Logs in to the karaoke-version.com website using provided credentials."""
        logger.info(f"Logging in as user: {self.username}")
        login_url = f"{self.base_url}/my/login.html"
        try:
            response = self.session.post(login_url,
                                         data={
                                             "frm_login": self.username,
                                             "frm_password": self.password
                                         })
            if response.status_code == 200 and "logout" in response.text.lower(
            ):
                logger.info("Login successful.")
            else:
                raise Exception("Login failed. Check credentials.")
        except Exception as e:

            logger.error(f"Login failed: {e}")
            raise

    def change_file_format(self, dl_id, kar_format="3-1-10507374"):
        """Changes the karaoke file format for a given download ID."""
        change_format_url = f"{self.base_url}/my/changeformat.html"
        params = {
            "dl_id": dl_id,
            "method": "ajax",
            "kar_format": kar_format,
            "applyall": "on"
        }
        headers = {
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Priority": "u=3, i",
            "User-Agent":
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.3 Safari/605.1.15",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{self.base_url}/my/download.html",
            "Referrer-Policy": "strict-origin-when-cross-origin"
        }

        try:
            response = self.session.get(change_format_url,
                                        params=params,
                                        headers=headers,
                                        allow_redirects=True)
            if response.status_code == 200:
                logger.info(
                    f"File format successfully changed for download ID {dl_id}."
                )
            else:
                logger.error(
                    f"Failed to change file format. Status code: {response.status_code}"
                )
                logger.debug(f"Response text: {response.text}")
        except Exception as e:

            logger.error(f"Error changing file format: {e}")

    def scrape_songs_on_page(self, page_number, max_retries=3):
        """Scrapes song data from a single page of the 'My Downloads' section with retry logic."""
        page_url = f"{self.base_url}/my/download.html?m=a&orderField=add_date&orderSort=desc&type=2&page={page_number}"

        for attempt in range(max_retries):
            try:
                response = self.session.get(page_url, timeout=30)
                response.raise_for_status()

                soup = BeautifulSoup(response.text, "html.parser")
                purchased_songs = soup.findAll("tr", {"class": "vam"})
                songs = []

                for song_row in purchased_songs:
                    try:
                        song_data = self._extract_song_data(song_row)
                        if song_data:
                            songs.append(song_data)
                    except Exception as e:
                        logger.warning(
                            f"Failed to extract song data from row: {e}")
                        continue

                next_link = soup.find("a", {"rel": "next", "class": "next"})
                has_next_page = next_link is not None
                return songs, has_next_page

            except Exception as e:
                logger.warning(
                    f"Attempt {attempt + 1} failed for page {page_number}: {e}"
                )
                if attempt == max_retries - 1:
                    logger.error(
                        f"All attempts failed for page {page_number}: {e}")
                    return [], False
                time.sleep(2**attempt)  # Exponential backoff

        return [], False

    def _extract_song_data(self, song_row):
        """Extract song data from a table row with error handling."""
        song_td = song_row.find("td", {"class": "my-downloaded-files__song"})
        if not song_td:
            raise ValueError("Song td not found")

        artist_td = song_td.find_next_sibling("td")
        if not artist_td:
            raise ValueError("Artist td not found")

        date_td = artist_td.find_next_sibling(
            "td", {"class": "my-downloaded-files__date"})

        song_anchor = song_td.find("a")
        if not song_anchor:
            raise ValueError("Song anchor not found")

        song_name = song_anchor.text.strip()
        song_url = song_anchor.get("href")
        artist_name = artist_td.text.strip()

        artist_anchor = artist_td.find("a")
        artist_url = artist_anchor.get("href") if artist_anchor else None
        date = intelligent_date_parse(
            date_td.text.strip()) if date_td else None

        download_link_anchor = song_row.find(
            "a", {"class": "my-downloaded-files__action"})
        if not download_link_anchor:
            raise ValueError("Download link not found")
        download_link = download_link_anchor.get("href")

        song_id_td = song_row.find("button",
                                   {"class": "my-downloaded-files__vote"})
        song_id_val = song_id_td.get("data-songid") if song_id_td else None
        song_id = f"KV{song_id_val}" if song_id_val else None

        if not song_id or not song_name or not artist_name:
            raise ValueError("Missing required song data")

        return {
            "song_id": song_id,
            "artist": artist_name,
            "artist_url": artist_url,
            "title": song_name,
            "title_url": song_url,
            "order_date": date,
            "download_url": download_link
        }

    def get_total_pages(self):
        """Determines the total number of pages in 'My Downloads' using pagination links."""
        try:
            response = self.session.get(
                f"{self.base_url}/my/download.html?m=a&orderField=add_date&orderSort=desc&type=2&page=9999"
            )
            soup = BeautifulSoup(response.text, "html.parser")
            pagination = soup.find("div", class_="pagination")
            if pagination:
                page_numbers = [
                    int(a.text)
                    for a in pagination.find_all("a", class_="hidden-xs")
                    if a.text.isdigit()
                ]
                return max(page_numbers) if page_numbers else 1
            return 1
        except Exception as e:

            logger.error(f"Error determining total pages: {e}")
            return 1

    def scrape_all_pages(self,
                         last_song_id=None,
                         validate=False,
                         progress_callback=None):
        """Scrapes song data from all pages of 'My Downloads', handling pagination and last song ID if provided."""
        total_pages = self.get_total_pages()
        all_songs = []
        found_last_song = False
        completed_pages = 0
        failed_pages = []

        def process_page(page_num):
            return self.scrape_songs_on_page(page_num)

        # Reduce max workers to avoid overwhelming the server
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {
                executor.submit(process_page, page): page
                for page in range(1, total_pages + 1)
            }

            for future in as_completed(futures):
                page_number = futures[future]
                completed_pages += 1

                try:
                    songs, _ = future.result(timeout=60)  # Add timeout

                    for song in songs:
                        if last_song_id and song[
                                "song_id"] == last_song_id and not validate:
                            found_last_song = True
                            break
                        all_songs.append(song)

                    if progress_callback:
                        progress = int((completed_pages / total_pages) * 100)
                        progress_callback(
                            progress,
                            f"Scraped page {completed_pages}/{total_pages}")

                    if found_last_song:
                        logger.info(
                            f"Found last song ID {last_song_id}, stopping scrape"
                        )
                        break

                except Exception as e:
                    logger.error(f"Error scraping page {page_number}: {e}")
                    failed_pages.append(page_number)

                    if progress_callback:
                        progress = int((completed_pages / total_pages) * 100)
                        progress_callback(
                            progress,
                            f"Failed page {page_number}, continuing...")

        if failed_pages:
            logger.warning(
                f"Failed to scrape {len(failed_pages)} pages: {failed_pages}")

        logger.info(
            f"Scraping completed: {len(all_songs)} songs found, {len(failed_pages)} pages failed"
        )
        return all_songs
