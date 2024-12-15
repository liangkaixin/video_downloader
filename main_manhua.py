import json
import os

import re
from typing import Tuple
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
from tenacity import retry, stop_after_attempt, wait_fixed
from PIL import Image
import requests
from io import BytesIO


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
        return self.source_codes

    def _page_urls(self):
        res = requests.get(self.request_url, headers=headers)
        soup = BeautifulSoup(res.text, 'html.parser')
        pattern = re.compile(r'^/index.php/chapter/*')  # 匹配符合条件的 href 格式
        links = soup.find_all(name='a', href=pattern)
        # 提取并打印所有符合条件的 href 链接
        self.urls = {link.text.strip(): scheme_host + link.get('href') for link in links}

    @staticmethod
    def _parse_download_url(title, url) -> Tuple[str, list]:
        try:
            res = requests.get(url, headers=headers)
            soup = BeautifulSoup(res.text, 'html.parser')
            # 查找 <script> 标签
            script_tags = soup.find_all('img', {'data-original': True})
            return title, [script_tag['data-original'] for script_tag in script_tags]
        except Exception as e:
            pass


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
        self.concatenate_images()

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
    def _download_ts(self, url, output_dir, title):
        try:
            response = requests.get(url, stream=True)
            response.raise_for_status()
            img = Image.open(BytesIO(response.content))
            file_name = f"{output_dir}/{title}_{url.rsplit('-', 1)[-1].rsplit('.', 1)[0]}.png"
            img.save(file_name, 'PNG')
            print(f"Downloaded: {file_name}")
            if [title, url] in self.retry_list:
                self.retry_list.remove([title, url])
            return 1
        except Exception as e:
            self.retry_list.append([title, url])
            print(f"Error downloading index {title}: {e}")
            return None

    def _download_all_ts(self):
        retry_times = self.retry_times
        os.makedirs(self.output_dir, exist_ok=True)

        with ThreadPoolExecutor(self.max_threads) as executor:
            for title, urls in self.ts_urls.items():
                futures = [executor.submit(self._download_ts, url, self.output_dir, title) for url in urls]
                for future in futures:
                    result = future.result()
                    if result:
                        self.ts_list.append(result)
        while self.retry_list and retry_times > 0:
            retry_times -= 1
            for title, url in self.retry_list:
                with ThreadPoolExecutor(self.max_threads) as executor:
                    print(f"Start retrying, {self.retry_list}")
                    futures = [executor.submit(self._download_ts, url, self.output_dir, title)]
                    for future in futures:
                        result = future.result()
                        if result:
                            self.ts_list.append(result)

    def concatenate_images(self, mode='vertical'):
        """
        拼接多张图片
        :param image_paths: 图片路径列表
        :param output_path: 输出文件路径
        :param mode: 拼接模式 ('horizontal' 或 'vertical')
        """
        os.chdir(self.output_dir)
        # 打开所有图片
        images = [Image.open(image_path) for image_path in self.ts_sorted_list]

        # 获取宽度和高度
        widths, heights = zip(*(img.size for img in images))

        if mode == 'horizontal':
            # 计算拼接后的总宽度和高度
            total_width = sum(widths)
            max_height = max(heights)
            new_image = Image.new('RGB', (total_width, max_height))

            # 拼接图片
            x_offset = 0
            for img in images:
                new_image.paste(img, (x_offset, 0))
                x_offset += img.width
        elif mode == 'vertical':
            # 计算拼接后的总宽度和高度
            max_width = max(widths)
            total_height = sum(heights)
            new_image = Image.new('RGB', (max_width, total_height))

            # 拼接图片
            y_offset = 0
            for img in images:
                new_image.paste(img, (0, y_offset))
                y_offset += img.height
        else:
            raise ValueError("mode 参数必须是 'horizontal' 或 'vertical'")

        # 保存拼接后的图片
        new_image.save('total.png')
        print(f"拼接完成，图片保存到：{self.output_dir}")

    def get_natural_sorted_filenames(self):
        try:
            all_files = os.listdir(self.output_dir)
            files_only = [f for f in all_files if
                          os.path.isfile(os.path.join(self.output_dir, f)) and f.endswith('.png')]
            sorted_files = sorted(
                files_only,
                key=lambda f: [
                    int(num) for num in re.findall(r'\d+', f)
                ]
            )
            return sorted_files
        except Exception as e:
            print(f"Error reading folder: {e}")
            return []


if __name__ == '__main__':
    DOWNLOAD_PATH = "./comics_files"
    url_origin = 'https://aicomic.org/index.php/comic/xihuanlaizhebujudeni'
    parsed_url = urlparse(url_origin)
    scheme_host = f"{parsed_url.scheme}://{parsed_url.netloc}"
    path = urlparse(url_origin).path
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}

    down_web = DownWeb(headers, url_origin)
    books_urls = down_web.process()
    down_ts = DownTs(books_urls, DOWNLOAD_PATH)
    down_ts.process()
