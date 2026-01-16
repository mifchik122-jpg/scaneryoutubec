import requests
import json
import re
import time
import csv
from datetime import datetime
from urllib.parse import urlparse, urljoin, parse_qs
import os
import sys
import textwrap
from typing import Dict, List, Optional, Tuple
import threading
from queue import Queue

class YouTubeAdvancedScanner:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        })
        self.results = []
        self.videos_queue = Queue()
        self.running = False
        
    def normalize_url(self, url: str) -> str:
        """Автоматически добавляет https:// если нужно"""
        url = url.strip()
        
        # Удаляем лишние пробелы
        url = re.sub(r'\s+', '', url)
        
        # Если нет протокола - добавляем https://
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        # Если это канал без @ или channel
        if 'youtube.com/' in url and not any(x in url for x in ['@', 'channel/', 'user/', 'c/']):
            if '/watch?v=' in url:
                # Это видео - оставляем как есть
                pass
            else:
                # Пытаемся понять что это
                if '/feed/' in url:
                    pass
                elif '/playlist' in url:
                    pass
                else:
                    print(f"⚠️  Непонятный URL формат: {url}")
        
        return url
    
    def determine_url_type(self, url: str) -> str:
        """Определяет тип URL: канал, видео или плейлист"""
        url_lower = url.lower()
        
        if '/watch?v=' in url:
            return 'video'
        elif '/channel/' in url or '/@' in url or '/user/' in url or '/c/' in url:
            return 'channel'
        elif '/playlist' in url:
            return 'playlist'
        elif 'youtube.com/' in url:
            # Проверяем, может быть это короткая ссылка на канал
            parsed = urlparse(url)
            path = parsed.path.strip('/')
            if path and not any(x in path for x in ['watch', 'feed', 'playlist']):
                return 'possible_channel'
        
        return 'unknown'
    
    def extract_channel_id_from_url(self, url: str) -> Optional[str]:
        """Извлекает ID канала из URL"""
        patterns = [
            r'youtube\.com/channel/([^/?&]+)',
            r'youtube\.com/@([^/?&]+)',
            r'youtube\.com/c/([^/?&]+)',
            r'youtube\.com/user/([^/?&]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url, re.IGNORECASE)
            if match:
                return match.group(1)
        
        # Пробуем получить ID через API-like запрос
        try:
            response = self.session.get(url, timeout=5)
            # Ищем channelId в странице
            match = re.search(r'"channelId":"([^"]+)"', response.text)
            if match:
                return match.group(1)
        except:
            pass
        
        return None
    
    def extract_video_id_from_url(self, url: str) -> Optional[str]:
        """Извлекает ID видео из URL"""
        patterns = [
            r'youtube\.com/watch\?v=([^&]+)',
            r'youtu\.be/([^?]+)',
            r'youtube\.com/embed/([^?]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url, re.IGNORECASE)
            if match:
                return match.group(1)
        
        return None
    
    def get_page_json(self, url: str) -> Optional[Dict]:
        """Получает JSON данные со страницы"""
        try:
            response = self.session.get(url, timeout=10)
            
            if response.status_code != 200:
                print(f"❌ HTTP ошибка {response.status_code}")
                return None
            
            # Ищем основной JSON
            patterns = [
                r'var ytInitialData\s*=\s*({.*?});',
                r'window\["ytInitialData"\]\s*=\s*({.*?});',
                r'ytInitialData\s*=\s*({.*?});',
            ]
            
            for pattern in patterns:
                match = re.search(pattern, response.text, re.DOTALL)
                if match:
                    try:
                        return json.loads(match.group(1))
                    except:
                        continue
            
            return None
            
        except Exception as e:
            print(f"❌ Ошибка загрузки: {e}")
            return None
    
    def scan_channel(self, channel_url: str, depth: int = 20) -> Dict:
        """Полное сканирование канала"""
        print(f"\n🔍 Начинаем сканирование канала...")
        
        channel_data = {
            'url': channel_url,
            'scan_time': datetime.now().isoformat(),
            'type': 'channel',
            'videos': [],
            'stats': {},
            'success': False
        }
        
        try:
            # Шаг 1: Получаем основную информацию о канале
            print("📋 Получаем информацию о канале...")
            channel_info = self.get_channel_info(channel_url)
            
            if not channel_info.get('success'):
                print("❌ Не удалось получить информацию о канале")
                return channel_data
            
            channel_data.update(channel_info)
            channel_data['success'] = True
            
            # Шаг 2: Получаем список видео
            print("🎬 Ищем видео на канале...")
            videos = self.get_channel_videos(channel_url, max_videos=depth)
            
            if videos:
                print(f"📊 Найдено {len(videos)} видео")
                channel_data['videos'] = videos
                
                # Шаг 3: Детальный анализ каждого видео
                print("\n📈 Анализируем каждое видео...")
                for i, video in enumerate(videos, 1):
                    print(f"  [{i}/{len(videos)}] Анализ: {video.get('title', 'Без названия')[:40]}...")
                    
                    video_details = self.get_video_details(video['id'])
                    if video_details:
                        video.update(video_details)
                    
                    # Небольшая пауза чтобы не получить блокировку
                    if i % 5 == 0:
                        time.sleep(1)
            
            # Шаг 4: Собираем общую статистику
            print("\n📊 Собираем общую статистику...")
            total_stats = self.calculate_total_stats(channel_data['videos'])
            channel_data['total_stats'] = total_stats
            
            print(f"\n✅ Сканирование завершено!")
            print(f"   📺 Видео проанализировано: {len(channel_data['videos'])}")
            print(f"   👍 Всего лайков: {total_stats.get('total_likes', 0):,}")
            print(f"   💬 Всего комментариев: {total_stats.get('total_comments', 0):,}")
            print(f"   👁️ Всего просмотров: {total_stats.get('total_views', 0):,}")
            
        except Exception as e:
            print(f"❌ Ошибка сканирования: {e}")
            channel_data['error'] = str(e)
        
        return channel_data
    
    def get_channel_info(self, url: str) -> Dict:
        """Получает базовую информацию о канале"""
        json_data = self.get_page_json(url)
        
        if not json_data:
            return {'success': False}
        
        info = {'success': True}
        
        try:
            # Ищем метаданные канала
            paths_to_check = [
                ['metadata', 'channelMetadataRenderer'],
                ['header', 'c4TabbedHeaderRenderer'],
            ]
            
            for path in paths_to_check:
                data = self._find_in_structure(json_data, path)
                if data:
                    if 'title' in data:
                        info['name'] = data['title']
                    if 'description' in data:
                        info['description'] = data['description']
                    if 'subscriberCountText' in data:
                        info['subscribers'] = data['subscriberCountText'].get('simpleText', '')
                    break
            
            # Если не нашли в обычных местах, ищем в тексте
            if 'name' not in info:
                # Ищем в заголовке страницы
                match = re.search(r'<title>(.*?)</title>', str(json_data))
                if match:
                    title = match.group(1).replace(' - YouTube', '').strip()
                    info['name'] = title
            
            # Ищем статистику
            self._extract_channel_stats(json_data, info)
            
        except Exception as e:
            info['parse_error'] = str(e)
        
        return info
    
    def _extract_channel_stats(self, json_data: Dict, info: Dict):
        """Извлекает статистику канала из JSON"""
        # Ищем количество видео
        video_text = self._search_in_structure(json_data, 'видео')
        if video_text:
            match = re.search(r'(\d+)\s*видео', video_text, re.IGNORECASE)
            if match:
                info['video_count'] = int(match.group(1))
        
        # Ищем подписчиков
        sub_text = self._search_in_structure(json_data, 'подписчик')
        if sub_text:
            match = re.search(r'([\d\s,]+)\s*подписчик', sub_text, re.IGNORECASE)
            if match:
                info['subscribers'] = match.group(1).strip()
    
    def get_channel_videos(self, url: str, max_videos: int = 50) -> List[Dict]:
        """Получает список видео с канала"""
        videos = []
        
        try:
            # Получаем первую страницу
            json_data = self.get_page_json(url)
            if not json_data:
                return videos
            
            # Ищем видео в контенте
            video_items = self._find_video_items(json_data)
            
            for item in video_items[:max_videos]:
                video = self._parse_video_item(item)
                if video:
                    videos.append(video)
            
        except Exception as e:
            print(f"Ошибка получения видео: {e}")
        
        return videos
    
    def _find_video_items(self, data) -> List:
        """Рекурсивно ищет элементы видео в структуре"""
        items = []
        
        if isinstance(data, dict):
            # Проверяем, является ли этот элемент видео
            if 'videoId' in data and 'title' in data:
                items.append(data)
            
            # Рекурсивно ищем в значениях
            for value in data.values():
                if isinstance(value, (dict, list)):
                    items.extend(self._find_video_items(value))
        
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, (dict, list)):
                    items.extend(self._find_video_items(item))
        
        return items
    
    def _parse_video_item(self, item: Dict) -> Optional[Dict]:
        """Парсит информацию о видео из элемента"""
        try:
            video = {
                'id': item.get('videoId'),
                'url': f"https://youtube.com/watch?v={item.get('videoId')}",
            }
            
            # Извлекаем заголовок
            title_data = item.get('title', {})
            if isinstance(title_data, dict):
                runs = title_data.get('runs', [])
                if runs:
                    video['title'] = runs[0].get('text', '')
                else:
                    video['title'] = title_data.get('simpleText', '')
            else:
                video['title'] = str(title_data)
            
            # Извлекаем статистику
            if 'viewCountText' in item:
                view_data = item['viewCountText']
                if isinstance(view_data, dict):
                    video['views'] = view_data.get('simpleText', '')
            
            if 'publishedTimeText' in item:
                time_data = item['publishedTimeText']
                if isinstance(time_data, dict):
                    video['published'] = time_data.get('simpleText', '')
            
            # Извлекаем длительность
            if 'lengthText' in item:
                length_data = item['lengthText']
                if isinstance(length_data, dict):
                    video['duration'] = length_data.get('simpleText', '')
            
            return video
            
        except Exception as e:
            return None
    
    def get_video_details(self, video_id: str) -> Dict:
        """Получает детальную информацию о видео"""
        url = f"https://www.youtube.com/watch?v={video_id}"
        json_data = self.get_page_json(url)
        
        if not json_data:
            return {}
        
        details = {}
        
        try:
            # Ищем информацию о видео
            video_data = self._find_video_primary_info(json_data)
            
            if video_data:
                # Просмотры
                if 'viewCount' in video_data:
                    view_data = video_data['viewCount']
                    if isinstance(view_data, dict):
                        details['views'] = view_data.get('videoViewCountRenderer', {}).get('viewCount', {}).get('simpleText', '')
                
                # Лайки
                if 'videoActions' in video_data:
                    actions = video_data['videoActions']
                    if 'menuRenderer' in actions:
                        items = actions['menuRenderer'].get('topLevelButtons', [])
                        for item in items:
                            if 'segmentedLikeDislikeButtonRenderer' in item:
                                like_data = item['segmentedLikeDislikeButtonRenderer']
                                if 'likeButton' in like_data:
                                    like_text = like_data['likeButton']['toggleButtonRenderer']['defaultText'].get('simpleText', '')
                                    details['likes'] = like_text
            
            # Ищем комментарии
            comments_count = self._find_comments_count(json_data)
            if comments_count:
                details['comments'] = comments_count
            
        except Exception as e:
            details['error'] = str(e)
        
        return details
    
    def _find_video_primary_info(self, data) -> Optional[Dict]:
        """Находит основную информацию о видео"""
        return self._search_structure(data, 'videoPrimaryInfoRenderer')
    
    def _find_comments_count(self, data) -> Optional[str]:
        """Находит количество комментариев"""
        # Ищем текст с комментариями
        comments_text = self._search_in_structure(data, 'комментари')
        if comments_text:
            match = re.search(r'([\d\s,]+)\s*комментари', comments_text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        
        return None
    
    def scan_video(self, video_url: str) -> Dict:
        """Сканирование одного видео"""
        print(f"\n🎬 Сканируем видео...")
        
        video_id = self.extract_video_id_from_url(video_url)
        
        if not video_id:
            return {'success': False, 'error': 'Не удалось извлечь ID видео'}
        
        video_data = {
            'url': video_url,
            'id': video_id,
            'scan_time': datetime.now().isoformat(),
            'type': 'video',
            'success': False
        }
        
        try:
            # Получаем основную информацию
            details = self.get_video_details(video_id)
            video_data.update(details)
            
            # Получаем информацию о канале из видео
            json_data = self.get_page_json(video_url)
            if json_data:
                # Ищем информацию о канале
                channel_info = self._extract_channel_from_video(json_data)
                if channel_info:
                    video_data['channel'] = channel_info
            
            video_data['success'] = True
            
            print(f"\n✅ Видео проанализировано!")
            
        except Exception as e:
            video_data['error'] = str(e)
        
        return video_data
    
    def _extract_channel_from_video(self, json_data: Dict) -> Optional[Dict]:
        """Извлекает информацию о канале из данных видео"""
        try:
            # Ищем информацию о канале в видео
            channel_data = self._search_structure(json_data, 'videoOwnerRenderer')
            if channel_data:
                channel = {}
                
                # Название канала
                if 'title' in channel_data:
                    title_data = channel_data['title']
                    if 'runs' in title_data:
                        channel['name'] = title_data['runs'][0].get('text', '')
                    elif 'simpleText' in title_data:
                        channel['name'] = title_data['simpleText']
                
                # Подписчики
                if 'subscriberCountText' in channel_data:
                    sub_data = channel_data['subscriberCountText']
                    if 'simpleText' in sub_data:
                        channel['subscribers'] = sub_data['simpleText']
                
                # ID канала
                if 'navigationEndpoint' in channel_data:
                    nav = channel_data['navigationEndpoint']
                    if 'browseEndpoint' in nav:
                        channel['id'] = nav['browseEndpoint'].get('browseId')
                
                return channel
        except:
            pass
        
        return None
    
    def calculate_total_stats(self, videos: List[Dict]) -> Dict:
        """Вычисляет общую статистику по всем видео"""
        stats = {
            'total_videos': len(videos),
            'total_views': 0,
            'total_likes': 0,
            'total_comments': 0,
        }
        
        for video in videos:
            # Просмотры
            if 'views' in video and video['views']:
                views_text = video['views'].replace(' ', '').replace(',', '').replace('просмотр', '')
                try:
                    if 'тыс' in views_text.lower():
                        views = float(views_text.replace('тыс', '').replace(',', '.')) * 1000
                    elif 'млн' in views_text.lower():
                        views = float(views_text.replace('млн', '').replace(',', '.')) * 1000000
                    else:
                        views = int(re.sub(r'[^\d]', '', views_text))
                    stats['total_views'] += views
                except:
                    pass
            
            # Лайки
            if 'likes' in video and video['likes']:
                likes_text = video['likes'].replace(' ', '').replace(',', '')
                try:
                    if 'тыс' in likes_text.lower():
                        likes = float(likes_text.replace('тыс', '').replace(',', '.')) * 1000
                    elif 'млн' in likes_text.lower():
                        likes = float(likes_text.replace('млн', '').replace(',', '.')) * 1000000
                    else:
                        likes = int(re.sub(r'[^\d]', '', likes_text))
                    stats['total_likes'] += likes
                except:
                    pass
            
            # Комментарии
            if 'comments' in video and video['comments']:
                comments_text = video['comments'].replace(' ', '').replace(',', '')
                try:
                    if 'тыс' in comments_text.lower():
                        comments = float(comments_text.replace('тыс', '').replace(',', '.')) * 1000
                    elif 'млн' in comments_text.lower():
                        comments = float(comments_text.replace('млн', '').replace(',', '.')) * 1000000
                    else:
                        comments = int(re.sub(r'[^\d]', '', comments_text))
                    stats['total_comments'] += comments
                except:
                    pass
        
        return stats
    
    def display_results(self, data: Dict):
        """Красиво отображает результаты"""
        if not data.get('success'):
            print("❌ Не удалось получить данные")
            if 'error' in data:
                print(f"   Ошибка: {data['error']}")
            return
        
        print("\n" + "═" * 70)
        
        if data['type'] == 'channel':
            self._display_channel_results(data)
        elif data['type'] == 'video':
            self._display_video_results(data)
        
        print("═" * 70)
    
    def _display_channel_results(self, data: Dict):
        """Отображает результаты сканирования канала"""
        print("📊 РЕЗУЛЬТАТЫ СКАНИРОВАНИЯ КАНАЛА")
        print("═" * 70)
        
        # Информация о канале
        print(f"\n📺 КАНАЛ: {data.get('name', 'Неизвестно')}")
        print(f"🔗 URL: {data.get('url')}")
        print(f"👥 Подписчики: {data.get('subscribers', 'Нет данных')}")
        print(f"🎬 Видео на канале: {data.get('video_count', len(data.get('videos', [])))}")
        
        if 'description' in data and data['description']:
            print(f"\n📝 ОПИСАНИЕ:")
            desc = data['description']
            if len(desc) > 200:
                desc = desc[:197] + '...'
            wrapped = textwrap.fill(desc, width=65)
            for line in wrapped.split('\n'):
                print(f"   {line}")
        
        # Общая статистика
        if 'total_stats' in data:
            stats = data['total_stats']
            print(f"\n📈 ОБЩАЯ СТАТИСТИКА:")
            print(f"   📊 Видео проанализировано: {stats.get('total_videos', 0)}")
            print(f"   👁️ Всего просмотров: {stats.get('total_views', 0):,}")
            print(f"   👍 Всего лайков: {stats.get('total_likes', 0):,}")
            print(f"   💬 Всего комментариев: {stats.get('total_comments', 0):,}")
        
        # Детали по видео (первые 5)
        if 'videos' in data and data['videos']:
            print(f"\n🎥 ПОСЛЕДНИЕ ВИДЕО:")
            for i, video in enumerate(data['videos'][:5], 1):
                title = video.get('title', 'Без названия')
                if len(title) > 40:
                    title = title[:37] + '...'
                
                print(f"\n   {i}. {title}")
                print(f"      🔗 {video.get('url')}")
                
                if 'published' in video:
                    print(f"      📅 Опубликовано: {video['published']}")
                
                if 'views' in video:
                    print(f"      👁️ Просмотры: {video['views']}")
                
                if 'likes' in video:
                    print(f"      👍 Лайки: {video.get('likes', 'Нет данных')}")
                
                if 'comments' in video:
                    print(f"      💬 Комментарии: {video.get('comments', 'Нет данных')}")
                
                if 'duration' in video:
                    print(f"      ⏱️ Длительность: {video.get('duration')}")
    
    def _display_video_results(self, data: Dict):
        """Отображает результаты сканирования видео"""
        print("🎬 РЕЗУЛЬТАТЫ СКАНИРОВАНИЯ ВИДЕО")
        print("═" * 70)
        
        print(f"\n📺 ВИДЕО: {data.get('title', 'Без названия')}")
        print(f"🔗 URL: {data.get('url')}")
        
        if 'channel' in data:
            print(f"\n📢 КАНАЛ:")
            channel = data['channel']
            print(f"   🎯 Название: {channel.get('name', 'Неизвестно')}")
            if 'subscribers' in channel:
                print(f"   👥 Подписчики: {channel['subscribers']}")
            if 'id' in channel:
                print(f"   🆔 ID: {channel['id']}")
        
        print(f"\n📊 СТАТИСТИКА ВИДЕО:")
        
        if 'views' in data:
            print(f"   👁️ Просмотры: {data['views']}")
        
        if 'likes' in data:
            print(f"   👍 Лайки: {data.get('likes', 'Нет данных')}")
        
        if 'comments' in data:
            print(f"   💬 Комментарии: {data.get('comments', 'Нет данных')}")
        
        if 'published' in data:
            print(f"   📅 Опубликовано: {data['published']}")
        
        if 'duration' in data:
            print(f"   ⏱️ Длительность: {data['duration']}")
    
    def save_results(self, data: Dict, format: str = 'txt'):
        """Сохраняет результаты в файл"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        if data['type'] == 'channel':
            filename = f"youtube_channel_scan_{timestamp}.{format}"
        else:
            filename = f"youtube_video_scan_{timestamp}.{format}"
        
        try:
            if format == 'csv':
                self._save_csv(data, filename)
            else:
                self._save_txt(data, filename)
            
            print(f"\n💾 Результаты сохранены в: {filename}")
            
        except Exception as e:
            print(f"❌ Ошибка сохранения: {e}")
    
    def _save_txt(self, data: Dict, filename: str):
        """Сохраняет результаты в текстовый файл"""
        with open(filename, 'w', encoding='utf-8') as f:
            f.write("=" * 70 + "\n")
            f.write("YOUTUBE SCAN RESULTS\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 70 + "\n\n")
            
            if data['type'] == 'channel':
                f.write(f"CHANNEL: {data.get('name', 'Unknown')}\n")
                f.write(f"URL: {data.get('url')}\n")
                f.write(f"Subscribers: {data.get('subscribers', 'N/A')}\n")
                f.write(f"Total Videos: {len(data.get('videos', []))}\n\n")
                
                if 'description' in data:
                    f.write(f"DESCRIPTION:\n{data['description']}\n\n")
                
                if 'total_stats' in data:
                    stats = data['total_stats']
                    f.write("TOTAL STATISTICS:\n")
                    f.write(f"- Videos analyzed: {stats.get('total_videos', 0)}\n")
                    f.write(f"- Total views: {stats.get('total_views', 0):,}\n")
                    f.write(f"- Total likes: {stats.get('total_likes', 0):,}\n")
                    f.write(f"- Total comments: {stats.get('total_comments', 0):,}\n\n")
                
                if 'videos' in data and data['videos']:
                    f.write("VIDEOS DETAILS:\n")
                    f.write("-" * 50 + "\n")
                    for i, video in enumerate(data['videos'], 1):
                        f.write(f"\n{i}. {video.get('title', 'No title')}\n")
                        f.write(f"   URL: {video.get('url')}\n")
                        if 'published' in video:
                            f.write(f"   Published: {video['published']}\n")
                        if 'views' in video:
                            f.write(f"   Views: {video['views']}\n")
                        if 'likes' in video:
                            f.write(f"   Likes: {video.get('likes', 'N/A')}\n")
                        if 'comments' in video:
                            f.write(f"   Comments: {video.get('comments', 'N/A')}\n")
                        if 'duration' in video:
                            f.write(f"   Duration: {video.get('duration')}\n")
            
            elif data['type'] == 'video':
                f.write(f"VIDEO: {data.get('title', 'Unknown')}\n")
                f.write(f"URL: {data.get('url')}\n\n")
                
                if 'channel' in data:
                    f.write("CHANNEL INFO:\n")
                    channel = data['channel']
                    f.write(f"- Name: {channel.get('name', 'Unknown')}\n")
                    if 'subscribers' in channel:
                        f.write(f"- Subscribers: {channel['subscribers']}\n")
                    f.write("\n")
                
                f.write("VIDEO STATISTICS:\n")
                if 'views' in data:
                    f.write(f"- Views: {data['views']}\n")
                if 'likes' in data:
                    f.write(f"- Likes: {data.get('likes', 'N/A')}\n")
                if 'comments' in data:
                    f.write(f"- Comments: {data.get('comments', 'N/A')}\n")
                if 'published' in data:
                    f.write(f"- Published: {data['published']}\n")
                if 'duration' in data:
                    f.write(f"- Duration: {data['duration']}\n")
    
    def _save_csv(self, data: Dict, filename: str):
        """Сохраняет результаты в CSV файл"""
        with open(filename, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            
            if data['type'] == 'channel':
                # Заголовок канала
                writer.writerow(['YOUTUBE CHANNEL SCAN RESULTS'])
                writer.writerow([f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"])
                writer.writerow([])
                writer.writerow(['CHANNEL INFORMATION'])
                writer.writerow(['Name', 'URL', 'Subscribers', 'Total Videos'])
                writer.writerow([
                    data.get('name', ''),
                    data.get('url', ''),
                    data.get('subscribers', ''),
                    len(data.get('videos', []))
                ])
                writer.writerow([])
                
                if 'videos' in data and data['videos']:
                    writer.writerow(['VIDEOS DETAILS'])
                    writer.writerow(['#', 'Title', 'URL', 'Published', 'Views', 'Likes', 'Comments', 'Duration'])
                    
                    for i, video in enumerate(data['videos'], 1):
                        writer.writerow([
                            i,
                            video.get('title', ''),
                            video.get('url', ''),
                            video.get('published', ''),
                            video.get('views', ''),
                            video.get('likes', ''),
                            video.get('comments', ''),
                            video.get('duration', '')
                        ])
    
    # Вспомогательные методы для поиска в структуре данных
    def _find_in_structure(self, data, path):
        """Находит данные по пути в структуре"""
        if not path:
            return data
        
        key = path[0]
        
        if isinstance(data, dict):
            if key in data:
                return self._find_in_structure(data[key], path[1:])
            else:
                for value in data.values():
                    if isinstance(value, (dict, list)):
                        result = self._find_in_structure(value, path)
                        if result:
                            return result
        
        elif isinstance(data, list):
            if isinstance(key, int) and 0 <= key < len(data):
                return self._find_in_structure(data[key], path[1:])
            else:
                for item in data:
                    if isinstance(item, (dict, list)):
                        result = self._find_in_structure(item, path)
                        if result:
                            return result
        
        return None
    
    def _search_structure(self, data, key_to_find):
        """Рекурсивно ищет ключ в структуре"""
        if isinstance(data, dict):
            if key_to_find in data:
                return data[key_to_find]
            for value in data.values():
                if isinstance(value, (dict, list)):
                    result = self._search_structure(value, key_to_find)
                    if result:
                        return result
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, (dict, list)):
                    result = self._search_structure(item, key_to_find)
                    if result:
                        return result
        return None
    
    def _search_in_structure(self, data, search_text):
        """Ищет текст в структуре"""
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, str) and search_text.lower() in value.lower():
                    return value
                elif isinstance(value, (dict, list)):
                    result = self._search_in_structure(value, search_text)
                    if result:
                        return result
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, (dict, list)):
                    result = self._search_in_structure(item, search_text)
                    if result:
                        return result
        return None

def main():
    print("=" * 70)
    print("🎬 YOUTUBE ADVANCED SCANNER v3.0")
    print("=" * 70)
    print("📋 Возможности:")
    print("   • Автоматическое добавление https://")
    print("   • Сканирование каналов и видео")
    print("   • Полный анализ лайков, комментариев, просмотров")
    print("   • Сохранение результатов в файлы")
    print("=" * 70)
    
    scanner = YouTubeAdvancedScanner()
    
    while True:
        print("\n📌 ГЛАВНОЕ МЕНЮ:")
        print("1. 🔍 Сканировать канал YouTube")
        print("2. 🎬 Сканировать одно видео")
        print("3. 📁 Сканировать несколько URL из файла")
        print("4. ❌ Выход")
        
        choice = input("\nВаш выбор (1-4): ").strip()
        
        if choice == '1':
            url = input("\nВведите ссылку на канал YouTube: ").strip()
            if url:
                # Нормализуем URL
                url = scanner.normalize_url(url)
                print(f"🔄 Анализируем: {url}")
                
                # Запрашиваем глубину сканирования
                depth = input("Сколько видео анализировать (по умолчанию 20): ").strip()
                depth = int(depth) if depth.isdigit() else 20
                
                # Сканируем канал
                data = scanner.scan_channel(url, depth=depth)
                
                # Показываем результаты
                scanner.display_results(data)
                
                # Сохраняем результаты
                if data.get('success'):
                    save = input("\n💾 Сохранить результаты? (да/нет): ").strip().lower()
                    if save in ['да', 'д', 'y', 'yes']:
                        format_choice = input("Формат (txt/csv): ").strip().lower()
                        format_choice = format_choice if format_choice in ['txt', 'csv'] else 'txt'
                        scanner.save_results(data, format_choice)
            else:
                print("⚠️ Введите ссылку!")
        
        elif choice == '2':
            url = input("\nВведите ссылку на видео YouTube: ").strip()
            if url:
                url = scanner.normalize_url(url)
                print(f"🔄 Анализируем видео: {url}")
                
                data = scanner.scan_video(url)
                scanner.display_results(data)
                
                if data.get('success'):
                    save = input("\n💾 Сохранить результаты? (да/нет): ").strip().lower()
                    if save in ['да', 'д', 'y', 'yes']:
                        scanner.save_results(data)
            else:
                print("⚠️ Введите ссылку!")
        
        elif choice == '3':
            filename = input("\nВведите имя файла с URL (txt): ").strip()
            if filename:
                try:
                    with open(filename, 'r', encoding='utf-8') as f:
                        urls = [line.strip() for line in f if line.strip()]
                    
                    print(f"\n📋 Найдено {len(urls)} URL для сканирования")
                    
                    for i, url in enumerate(urls, 1):
                        print(f"\n[{i}/{len(urls)}] Сканирование: {url}")
                        url = scanner.normalize_url(url)
                        
                        url_type = scanner.determine_url_type(url)
                        if url_type == 'channel':
                            data = scanner.scan_channel(url, depth=10)
                        elif url_type == 'video':
                            data = scanner.scan_video(url)
                        else:
                            print("❌ Неподдерживаемый тип URL")
                            continue
                        
                        scanner.display_results(data)
                        
                        # Пауза между запросами
                        if i < len(urls):
                            time.sleep(2)
                    
                except FileNotFoundError:
                    print("❌ Файл не найден!")
                except Exception as e:
                    print(f"❌ Ошибка: {e}")
        
        elif choice == '4':
            print("\n👋 До свидания!")
            break
        
        else:
            print("⚠️ Неверный выбор!")

if __name__ == "__main__":
    # Примеры использования:
    # scanner = YouTubeAdvancedScanner()
    
    # 1. Сканирование канала (автоматически добавит https://)
    # data = scanner.scan_channel("youtube.com/@fimahoma360")
    # scanner.display_results(data)
    
    # 2. Сканирование видео
    # data = scanner.scan_video("youtube.com/watch?v=VIDEO_ID")
    # scanner.display_results(data)
    
    main()
