# -*- coding: utf-8 -*-

import itertools
import json
import os
import re
import sys
import urllib
import urllib2

import xbmcaddon, xbmcgui, xbmcplugin
import sdLog, sdParser, sdCommon, sdNavigation, downloader


scriptID = sys.modules["__main__"].scriptID
scriptname = sys.modules["__main__"].scriptname
ptv = xbmcaddon.Addon(scriptID)

BASE_IMAGE_PATH = 'http://sd-xbmc.org/repository/xbmc-addons/'
BASE_RESOURCE_PATH = os.path.join(ptv.getAddonInfo('path'), "../resources")
sys.path.append(os.path.join(BASE_RESOURCE_PATH, "lib"))

log = sdLog.pLog()

dstpath = ptv.getSetting('default_dstpath')
dbg = sys.modules["__main__"].dbg

username = ptv.getSetting('kinoman_login')
password = ptv.getSetting('kinoman_password')

SERVICE = 'kinoman'
LOGOURL = BASE_IMAGE_PATH + SERVICE + '.png'
COOKIEFILE = ptv.getAddonInfo('path') + os.path.sep + "cookies" + os.path.sep + SERVICE + ".cookie"
THUMB_NEXT = BASE_IMAGE_PATH + "dalej.png"


SERVICE_MENU_TABLE = {
    1: "Kategorie filmowe",
    2: "Typy filmów",
    3: "Ostatnio dodane",
    4: "Najwyżej ocenione",
    5: "Najczęściej oceniane",
    6: "Najczęściej oglądane",
    7: "Ulubione",
    8: "Najnowsze",
    9: "Seriale",
    10: "Wyszukaj",
    11: "Historia wyszukiwania"
}


class KinomanAPI(object):
    BASE_URL = 'http://kinoman.tv'
    API_URL = 'http://api.lajt.kinoman.tv/api'
    CACHE_URL = 'http://cache.lajt.kinoman.tv/api'

    def __init__(self, username=None, password=None, vars_file='kinoman_token.txt'):
        self.vars_file = vars_file
        self._movie_filter = None
        self.opener = urllib2.build_opener()
        self.opener.addheaders = [('User-agent', 'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/52.0.2743.116 Safari/537.36')]
        self.free_player = True
        self.user_token = ''
        if username and password:
            try:
                self._load_vars()
                # check if user logged in correctly, re-login if needed (invalid token, etc.)
                assert self.user()['username'] != ''
            except (IOError, ValueError, urllib2.HTTPError):
                self._login_get_token(username, password)
            self.free_player = False

    def _login_get_token(self, username, password):
        r = self._api_post('/user/login', {"username": username, "password": password})
        self.user_token = r['token']
        self._save_vars()

    def _save_vars(self):
        with open(self.vars_file, 'w') as f:
            f.write(self.user_token)

    def _load_vars(self):
        with open(self.vars_file) as f:
            self.user_token = f.read()

    def _api_post(self, path, data):
        r = self.opener.open(self.API_URL + path, data=json.dumps(data)).read()
        return json.loads(r)

    def _api_post_token(self, path, data=None):
        d = {'token': urllib.unquote(self.user_token)}
        if data:
            d.update(data)
        return self._api_post(path + '?userToken=%s' % self.user_token, d)

    def _cache_get(self, path, query=None):
        if query and not isinstance(query, basestring):
            q = []
            for k in query:
                try:
                    v = query[k]
                except KeyError:
                    k, v = k
                if v is not None:
                    q.append((k, v))
            query = urllib.urlencode(q)
        query = ('?' + query) if query else ''
        r = self.opener.open(self.CACHE_URL + path + query).read()
        return json.loads(r)

    def _link(self, **kwargs):
        return self._api_post_token('/link', data=kwargs)

    def _player_action(self, action, **kwargs):
        kwargs['action'] = action
        return self._api_post_token('/player/get', data=kwargs)

    def user(self):
        return self._api_post_token('/user/getUser')

    def icon_url(self, item, small=False):
        hash = item['hash']
        a, b, c = hash[0:4], hash[4:6], hash[6:8]
        return 'http://static.kinoman.tv/s/c/%s/%s/%s/%s.jpg' % (a, b, c, 'm' if small else 'o')

    def movies(self, filters=None):
        """
        Get movies list based on filter criteria and offset.
        :param filters: genre[]=<genre_id>, quality[]=1-3 (3-highest), type[]=1-5, offset=<num>, limit=<num>, order[col]=<column to sort>, order[dir]=asc/desc
        :return: List of movies.
        """
        if filters is None:
            filters = []
        return self._cache_get('/movie', '&'.join(filters))

    def movie_filter(self, filter=None):
        """
        Lists movie filter choices.
        :param filter: 'genres', 'genres_byKey', 'types', 'types_byKey' or None for all types in single dict.
        :return:
        """
        if not self._movie_filter:
            self._movie_filter = self._cache_get('/movie_filter')
        if filter:
            return self._movie_filter[filter]
        return self._movie_filter

    def url_from_link_code(self, code):
        if not self.free_player:
            hash = self._player_action('getHash', code=code)
            return self._player_action('getPlayerByHash', hash=hash)
        else:
            s = self._player_action('getFreePlayer', code=code)
            url = s.split('<iframe src="')[1].split('"')[0]
            r = self.opener.open(url).read()
            url = re.search(r'<div id="playerVidzer">[\s\S]+?href="(.+?)"[\s\S]+?id="player">', r).groups(1)[0]
            return url

    def movie_url(self, movie_id):
        code = self._link(movie_id=movie_id)[0]['code']
        return self.url_from_link_code(code)

    def series_index(self):
        return self._cache_get('/series_index')

    def series(self, filters=None):
        if filters is None:
            filters = []
        return self._cache_get('/series', '&'.join(filters))

    def episodes(self, series_id, limit=None):
        return self._cache_get('/episodes', {'series_id': series_id, 'limit': limit})

    def episode_url(self, episode_id):
        code = self._link(episode_id=episode_id)[0]['code']
        return self.url_from_link_code(code)


class Kinoman:
    def __init__(self):
        log.info('Loading ' + SERVICE)
        self.api = KinomanAPI(username, password, COOKIEFILE)
        self.parser = sdParser.Parser()
        self.cm = sdCommon.common()
        self.history = sdCommon.history()
        self.gui = sdNavigation.sdGUI()

    def endDir(self, type):
        if type == 'movies':
            listMask = '%P [[COLOR=white]%Y[/COLOR]] %R'
            viewMode = 'MediaInfo'
        elif type == 'episodes':
            listMask = '[[COLOR=white]%H [/COLOR]]%Z'
            viewMode = 'List'
        else:
            listMask = None
            viewMode = None
        if listMask:
            xbmcplugin.addSortMethod(int(sys.argv[1]), sortMethod=xbmcplugin.SORT_METHOD_NONE, label2Mask=listMask)
        self.gui.endDir(False, type, viewMode)

    def format_movie(self, item):
        params = {'service': SERVICE, 'type': 'movie', 'id': item['id']}
        params['year'] = item['year']
        params['rating'] = item['rate']
        params['votes'] = item['rate_cnt']
        params['title'] = (item['name'] or '').encode('utf-8')
        params['originaltitle'] = (item['orginal_name'] or '').encode('utf-8')
        params['icon'] = self.api.icon_url(item)
        params['fanart'] = self.api.icon_url(item)
        if item['genre_ids']:
            params['genre'] = ','.join(self.api.movie_filter('genres_byKey')[genre]['name'].encode('utf-8') for genre in item['genre_ids'].split(','))
        params['plot'] = (item['description'] or '').encode('utf-8')
        params['votes'] = item['fav_cnt']
        params['dstpath'] = dstpath
        # workaround for passing type and id for download ('page' is passed as 'url' and only it can be used and we don't want to retrieve urls for all items unnecessarily)
        params['page'] = 'movie:%s' % item['id']
        COLORS = ['', 'green', 'blue', 'yellow', 'lime', 'red']
        try:
            color = COLORS[int(item['type_id'])]
        except IndexError:
            color = 'red'
        params['code'] = '[COLOR=' + color + ']' + item['type_short'] + '[/COLOR]'
        return params

    def format_episode(self, item):
        params = {'service': SERVICE, 'type': 'episode', 'id': item['id']}
        params['season'] = item['season']
        params['episode'] = item['episode']
        params['tvshowtitle'] = (item['series_name'] or '').encode('utf-8')
        params['rating'] = item['series_rate']
        params['votes'] = item['series_rate_cnt']
        params['title'] = (item['name'] or '').encode('utf-8')
        params['originaltitle'] = (item['series_orginal_name'] or '').encode('utf-8')
        params['icon'] = self.api.icon_url(item)
        params['fanart'] = self.api.icon_url(item)
        params['plot'] = (item['series_description'] or '').encode('utf-8')
        params['votes'] = item['fav_cnt']
        params['dstpath'] = dstpath
        # workaround for passing type and id for download ('page' is passed as 'url' and only it can be used and we don't want to retrieve urls for all items unnecessarily)
        params['page'] = 'episode:%s' % item['id']
        return params

    def create_main_menu(self, table):
        for id, name in table.items():
            params = {'service': SERVICE, 'id': id, 'title': name, 'type': 'main-menu'}
            self.gui.addDir(params)
        self.gui.endDir()

    def create_movie_types_menu(self, filter):
        items = self.api.movie_filter(filter)
        filter_name = ''
        if filter == 'genres':
            filter_name = 'genre[]'
        elif filter == 'types':
            filter_name = 'type[]'
        for item in items:
            params = {'service': SERVICE, 'title': item['name'].encode('utf-8'), 'category': filter_name + '=' + item['id'], 'type': 'movie-type', 'icon': LOGOURL}
            self.gui.addDir(params)
        if filter == 'types':
            params = {'service': SERVICE, 'title': 'Filmy HD', 'category': 'quality[]=3', 'type': 'movie-type', 'icon': LOGOURL}
            self.gui.addDir(params)
        self.gui.endDir(True)

    def create_movies_menu(self, filter, page):
        limit = 50
        offset = page * limit
        filters = ['limit=%d' % limit, 'offset=%d' % offset]
        if filter:
            filters.append(filter)
        movies = self.api.movies(filters=filters)
        for movie in movies['rows']:
            params = self.format_movie(movie)
            self.gui.playVideo(params)
        if offset + limit < movies['cnt']:
            params = {'service': SERVICE, 'type': 'movie-nextpage', 'title': 'Następna strona', 'category': filter, 'page': str(page + 1), 'icon': THUMB_NEXT}
            self.gui.addDir(params)
        self.endDir('movies')

    def get_abc_series(self, series, filter):
        if filter == '0-9':
            series = [s for s in series if '0' <= s['name'][0] <= '9']
        else:
            filter = filter.decode('utf-8')
            series = [s for s in series if s['name'][0] == filter]
        return series

    def create_series_menu(self, filter):
        if '=' in filter:
            filters = [filter]
            series = self.api.series(filters)['rows']
        else:
            series = self.api.series()['rows']
            series = self.get_abc_series(series, filter)
        for serie in series:
            title = serie['name'].encode('utf-8')
            params = {'service': SERVICE, 'type': 'series-serie', 'tvshowtitle': title, 'title': title, 'id': serie['id'], 'icon': LOGOURL}
            self.gui.addDir(params)
        self.gui.endDir(False, 'tvshows')

    def create_series_abc_menu(self, table):
        for item in table:
            item = item.encode('utf-8')
            params = {'service': SERVICE, 'type': 'series-abc-menu', 'title': item, 'category': item, 'icon': ''}
            self.gui.addDir(params)
        self.gui.endDir()

    def create_history_menu(self, texts, type):
        for text in texts:
            if text:
                params = {'service': SERVICE, 'type': 'history', 'name': type, 'title': text, 'icon': ''}
                self.gui.addDir(params)
        self.gui.endDir()

    def get_episodes_by_season(self, episodes):
        keyfunc = lambda a: int(a['season'])
        episodes = sorted(episodes, key=keyfunc)
        result = {k: list(g) for k, g in itertools.groupby(episodes, keyfunc)}
        return result

    def create_seasons_menu(self, id):
        seasons_episodes = self.get_episodes_by_season(self.api.episodes(id)['rows'])
        for season, episodes in seasons_episodes.items():
            title = 'Sezon %d' % season
            params = {'service': SERVICE, 'type': 'series-episodes', 'id': id, 'season': season, 'tvshowtitle': episodes[0]['series_name'].encode('utf-8'), 'title': title, 'icon': ''}
            self.gui.addDir(params)
        self.gui.endDir(True)

    def create_episodes_menu(self, id, season):
        episodes = self.get_episodes_by_season(self.api.episodes(id)['rows'])
        episodes = episodes[season]
        for episode in episodes:
            params = self.format_episode(episode)
            self.gui.playVideo(params)
        self.endDir('episodes')

    def get_search_type(self):
        types = {'movies': 'Filmy', 'tvshows': 'Seriale'}
        index = xbmcgui.Dialog().select("Co chcesz znaleść?", types.values())
        if index >= 0:
            return types.keys()[index]
        return None

    def handleService(self):
        params = self.parser.getParams()
        id = int(self.parser.getParam(params, "id") or 0)
        name = self.parser.getParam(params, "name")
        title = self.parser.getParam(params, "title")
        type = self.parser.getParam(params, "type")
        category = self.parser.getParam(params, "category")
        page = self.parser.getParam(params, "page")
        if not page:
            page = 0
        season = int(self.parser.getParam(params, "season") or 0)
        action = self.parser.getParam(params, "action")
        path = self.parser.getParam(params, "path")
        url = self.parser.getParam(params, "url")

        self.parser.debugParams(params, dbg)

        # MAIN MENU
        if type is None:
            self.create_main_menu(SERVICE_MENU_TABLE)
        elif type == 'main-menu':
            if id == 1:
                # KATEGORIE FILMOWE
                self.create_movie_types_menu('genres')
            elif id == 2:
                # TYPY FILMÓW
                self.create_movie_types_menu('types')
            elif id == 3:
                # OSTATNIO DODANE
                self.create_movies_menu('', page)
            elif id == 4:
                # NAJWYŻEJ OCENIONE
                self.create_movies_menu('order[col]=rate&order[dir]=desc', page)
            elif id == 5:
                # NAJCZĘŚCIEJ OCENIANE
                self.create_movies_menu('order[col]=rate_cnt&order[dir]=desc', page)
            elif id == 6:
                # NAJCZĘŚCIEJ OGLĄDANE
                self.create_movies_menu('order[col]=views&order[dir]=desc', page)
            elif id == 7:
                # ULUBIONE
                self.create_movies_menu('order[col]=fav_cnt&order[dir]=desc', page)
            elif id == 8:
                # NAJNOWSZE
                self.create_movies_menu('order[col]=year&order[dir]=desc', page)
            elif id == 9:
                # SERIALE
                letters = u'AĄBCĆDEĘFGHIJKLŁMNŃOÓPQRSŚTUVWXYZŻŹ'
                self.create_series_abc_menu(['0-9'] + list(letters))
            elif id == 10:
                # WYSZUKAJ
                type = self.get_search_type()
                if type:
                    text = self.gui.searchInput(SERVICE + type)
                    if text:
                        if type == 'movies':
                            self.create_movies_menu('name_like=%s' % text, page)
                        elif type == 'tvshows':
                            self.create_series_menu('name_like=%s' % text)
            elif id == 11:
                # HISTORIA WYSZUKIWANIA
                type = self.get_search_type()
                if type:
                    texts = self.history.loadHistoryFile(SERVICE + type)
                    self.create_history_menu(texts, type)

        elif type in ['movie-type', 'movie-nextpage']:
            self.create_movies_menu(category, page)
        elif type == 'series-abc-menu':
            self.create_series_menu(category)
        elif type == 'series-serie':
            self.create_seasons_menu(id)
        elif type == 'series-episodes':
            self.create_episodes_menu(id, season)
        elif type == 'history':
            if name == 'movies':
                self.create_movies_menu('name_like=%s' % title, page)
            elif name == 'tvshows':
                self.create_series_menu('name_like=%s' % title)

        if name == 'playSelectedVideo':
            if type == 'movie':
                link = self.api.movie_url(id)
                self.gui.LOAD_AND_PLAY_VIDEO(link, title)
            elif type == 'episode':
                link = self.api.episode_url(id)
                self.gui.LOAD_AND_PLAY_VIDEO(link, title)
        if action == 'download':
            # POBIERZ
            self.cm.checkDir(os.path.join(dstpath, SERVICE))
            type, id = url.split(':')
            id = int(id)
            link = None
            if type == 'movie':
                link = self.api.movie_url(id)
            elif type == 'episode':
                link = self.api.episode_url(id)
            if link:
                dwnl = downloader.Downloader()
                dwnl.getFile({'title': title, 'url': link, 'path': path})
