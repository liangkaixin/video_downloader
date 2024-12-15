import json
import os

import re
from typing import Tuple, Dict

import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
from tenacity import retry, stop_after_attempt, wait_fixed
import subprocess

class DownWeb:
    def __init__(self, fact_headers, request_url):
        self.headers = fact_headers
        self.request_url = request_url
        self.urls = {}
        self.source_codes = {}

    def process(self):
        self._page_urls()

        for title, url in self.urls.items():
            if len(self.source_codes) > 1:
                break
            title, url_dict = self._parse_download_url(title, url)
            if title:
                self.source_codes[title] = url_dict
        return self._ts_urls()

    def _page_urls(self):
        res = requests.get(self.request_url, headers=headers)
        soup = BeautifulSoup(res.text, 'html.parser')
        pattern = re.compile(r'^/index.php/vod/play/id/*')  # 匹配符合条件的 href 格式
        links = soup.find_all(name='a', href=pattern)
        # 提取并打印所有符合条件的 href 链接
        self.urls = {link.get('title'): hsck_origin + link.get('href') for link in links}

    @staticmethod
    def _parse_download_url(title, url) -> Tuple[str, Dict]:
        try:
            res = requests.get(url, headers=headers)
            soup = BeautifulSoup(res.text, 'html.parser')
            # 查找 <script> 标签
            script_tag = soup.find('script', string=re.compile('var player_aaaa'))

            # 提取 JavaScript 代码
            script_content = script_tag.string
            # 去掉 JavaScript 变量名部分，提取有效的 JSON 内容
            json_str = script_content.split('=')[1].strip().rstrip(';')
            # 使用正则表达式提取 url
            url = json.loads(json_str).get('url')
            if url and 'jinpin' not in url:
                if 'vip' not in url:
                    print(title, 'https://lbjx9.com/?url=' + url)
                    return title, {'video_url': 'https://lbjx9.com/?url=' + url, 'download_url': url}
                else:
                    # 使用正则表达式提取路径
                    match = re.search(r'(/[\w/.-]+\.m3u8)', requests.get(url).text)

                    # 使用 urlparse 解析 URL
                    origin_path = urlparse(url).path
                    real_path = urlparse(match.group(0)).path

                    url = url.replace(origin_path, real_path)
                    print(title, 'https://lbjx9.com/?url=' + url)
                    return title, {'video_url': 'https://lbjx9.com/?url=' + url, 'download_url': url}
        except Exception as e:
            pass

    def _ts_urls(self):
        ts_urls = []
        for _, url_dic in self.source_codes.items():
            print('开始拿取对应的视频片段')
            url = url_dic['download_url']
            try:
                res = requests.get(url)
                path = urlparse(url).path
                mat = re.findall(r'.*ts', res.text)
                for i in mat:
                    if '/' in i:
                        ts_urls.append(url.replace(path, i))
                    else:
                        ts_urls.append(url.replace(url.split('/')[-1], i))
            except Exception as e:
                pass
        return ts_urls


class DownTs:
    def __init__(self, ts_urls, output_dir, retry_times=3, max_threads=32):
        self.ts_urls = ts_urls
        self.output_dir = output_dir
        self.max_threads = max_threads
        self.retry_times = retry_times
        self.ts_sorted_list = []
        self.retry_list = []
        self.ts_list = []

    def process(self):
        self._download_all_ts()
        self.ts_sorted_list = self.get_natural_sorted_filenames()
        self.merge_ts_files()

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
    def _download_ts(self, url, output_dir, index):
        try:
            response = requests.get(url, stream=True)
            response.raise_for_status()
            ts_path = os.path.join(output_dir, f"{url.split('/')[-2]}_{index}.ts")
            with open(ts_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=1024):
                    if chunk:
                        f.write(chunk)
            print(f"Downloaded: {ts_path}")
            if [index, url] in self.retry_list:
                self.retry_list.remove([index, url])
            return ts_path
        except Exception as e:
            self.retry_list.append([index, url])
            print(f"Error downloading index {index}: {e}")
            return None

    def _download_all_ts(self):
        retry_times = self.retry_times
        os.makedirs(self.output_dir, exist_ok=True)

        with ThreadPoolExecutor(self.max_threads) as executor:
            futures = [executor.submit(self._download_ts, url, self.output_dir, i) for i, url in enumerate(ts_urls)]
            for future in futures:
                result = future.result()
                if result:
                    self.ts_list.append(result)
        while self.retry_list and retry_times > 0:
            retry_times -= 1
            with ThreadPoolExecutor(self.max_threads) as executor:
                print(f"Start retrying, {self.retry_list}")
                futures = [executor.submit(self._download_ts, url, self.output_dir, i) for i, url in self.retry_list]
                for future in futures:
                    result = future.result()
                    if result:
                        self.ts_list.append(result)

    def merge_ts_files(self):
        os.chdir(self.output_dir)
        file_names = set(ts.split('_')[0] for ts in self.ts_sorted_list)
        for file in file_names:
            with open(f'{file}.ts', 'wb') as merged:
                for ts_file in self.ts_sorted_list:
                    if file in ts_file:
                        with open(ts_file, 'rb') as ts:
                            merged.write(ts.read())
            print(f"Merged into: f'{file}.ts'")
            # Run FFmpeg command
            command = [
                "ffmpeg", "-f", "concat", "-safe", "0", "-i", f'{file}.ts', "-c", "copy", f'{file}.mp4'
            ]
            subprocess.run(command, check=True)
            print(f"Merged and converted to f'{file}.mp4'")




    def get_natural_sorted_filenames(self):
        try:
            all_files = os.listdir(self.output_dir)
            files_only = [f for f in all_files if
                          os.path.isfile(os.path.join(self.output_dir, f)) and f.endswith('.ts')]
            sorted_files = sorted(
                files_only,
                key=lambda f: int(re.search(r'_(\d+)\.ts', f).group(1)) if re.search(r'_(\d+)\.ts', f) else float('inf')
            )
            return sorted_files
        except Exception as e:
            print(f"Error reading folder: {e}")
            return []


if __name__ == '__main__':
    DOWNLOAD_PATH = "./video_files"

    hsck_origin = 'https://www.hsck.la/'
    hsck = 'https://www.hsck.la/index.php/vod/search.html?wd=玩偶姐姐'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}

    down_web = DownWeb(headers, hsck)
    ts_urls = down_web.process()

    down_ts = DownTs(ts_urls, DOWNLOAD_PATH)
    down_ts.process()
