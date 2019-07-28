# encoding: UTF-8


import numpy as np
import talib
import copy
from datetime import timedelta, datetime
import math
import re

from vnpy.trader.vtObject import VtBarData
# 规定周期
from vnpy.trader.vtConstant import *


INTERVAL_BACK2VT = {
    1: INTERVAL_1M,
    3: INTERVAL_3M,
    5: INTERVAL_5M,
    15: INTERVAL_15M,
    30: INTERVAL_30M,
    60: INTERVAL_60M,
    240: INTERVAL_240M,
}
INTERVAL_VT2BACK = {v: k for k, v in INTERVAL_BACK2VT.items()}

####
# 增
# 晚稻 鸡蛋 硅铁 锰硅 苹果 红枣
DAYGROUP_1500 = ['wr', 'jd', 'sf', 'sm', 'ap', 'cj']
# 塑料 PVC EG PP
# 螺纹 热卷 燃油 沥青 橡胶 纸浆
# 豆粕 豆油 豆一 豆二 棕榈油 玉米 玉米淀粉
# 焦炭 焦煤 铁矿
NIGHTGROUP_2300 = ['l', 'v', 'eg', 'pp',
                   'rb', 'hc', 'fu', 'bu', 'ru', 'sp',
                   'm', 'y', 'a', 'b', 'p', 'c', 'cs',
                   'j', 'jm', 'i']
# 白糖 棉花 棉纱 动力煤 玻璃 PTA 甲醇 菜油 菜粕
NIGHTGROUP_2330 = ['sr', 'cf', 'cy', 'zc', 'fg', 'ta', 'ma', 'oi', 'rm']
# 铜 铝 锌 铅 镍 锡
NIGHTGROUP_0100 = ['cu', 'al', 'zn', 'pb', 'ni', 'sn']
# 原油 黄金 白银
NIGHTGROUP_0230 = ['sc', 'au', 'ag']
COMMODITY = ['wr', 'jd', 'sf', 'sm', 'ap', 'cj',
             'l', 'v', 'eg', 'pp',
             'rb', 'hc', 'fu', 'bu', 'ru', 'sp',
             'm', 'y', 'a', 'b', 'p', 'c', 'cs',
             'j', 'jm', 'i',
             'sr', 'cf', 'cy', 'zc', 'fg', 'ta', 'ma', 'oi', 'rm',
             'cu', 'al', 'zn', 'pb', 'ni', 'sn',
             'sc', 'au', 'ag'
             ]
FINANCE = ["if", "ih", "ic", "t", "ts", "tf"]



########################################################################
class BarGenerator:
    """
    For:
    1. generating 1 minute bar data from tick data
    2. generateing x minute bar/x hour bar data from 1 minute data

    Notice:
    1. for x minute bar, x must be able to divide 60: 2, 3, 5, 6, 10, 15, 20, 30
    2. for x hour bar, x can be any number
    最后一个参数是合成分钟线还是合成小时线
    合成一小时线 用的Interval.MINUTE window=60
    """

    def __init__(
        self,
        on_bar,
        window: int = 0,
        on_window_bar=None,
        interval=INTERVAL_1M
    ):
        """Constructor"""
        # 只要不进tick,self.on_bar就不会调用
        # 也就是,如果是数字货币订阅官方bar,而不是本地合成那么on_bar的调用
        # 只会是CtaEngine里面process_bar_event 之后的分发,不是这里的本地调用
        self.on_bar = on_bar

        self.interval = interval
        self.interval_count = 0

        self.window = window
        self.window_bar = None
        self.on_window_bar = on_window_bar

        self.last_tick = None
        self.last_bar = None

    def update_tick(self, tick):
        """
        Update new tick data into generator.
        回测版本的update_tick尚未开发
        """
        return
        newMinute = False  # 默认不是新的一分钟

        # 尚未创建对象
        if not self.bar:
            self.bar = VtBarData()
            self.bar.interval = INTERVAL_1M
            newMinute = True
        # 新的一分钟
        elif self.bar.datetime.minute != tick.datetime.minute:
            # 生成上一分钟K线的时间戳
            self.bar.datetime = self.bar.datetime.replace(second=0, microsecond=0)  # 将秒和微秒设为0
            self.bar.date = self.bar.datetime.strftime('%Y%m%d')
            self.bar.time = self.bar.datetime.strftime('%H:%M:%S.%f')

            # 推送已经结束的上一分钟K线
            self.on_bar(self.bar)
            self.update_bar(self.bar)

            # 创建新的K线对象
            self.bar = VtBarData()
            self.bar.interval = INTERVAL_1M
            newMinute = True

        # 初始化新一分钟的K线数据
        if newMinute:
            self.bar.vtSymbol = tick.vtSymbol
            self.bar.symbol = tick.symbol
            self.bar.exchange = tick.exchange

            self.bar.open = tick.lastPrice
            self.bar.high = tick.lastPrice
            self.bar.low = tick.lastPrice

            # 生成一分钟K线的时间戳
            self.bar.datetime = tick.datetime.replace(second=0, microsecond=0)  # 将秒和微秒设为0
            self.bar.date = self.bar.datetime.strftime('%Y-%m-%d')
            self.bar.time = self.bar.datetime.strftime('%H:%M:%S.%f')
        # 累加更新老一分钟的K线数据
        else:
            self.bar.high = max(self.bar.high, tick.lastPrice)
            self.bar.low = min(self.bar.low, tick.lastPrice)

        # 通用更新部分
        self.bar.close = tick.lastPrice
        # self.bar.datetime = tick.datetime
        self.bar.openInterest = tick.openInterest

        if self.lastTick:
            volumeChange = tick.volume - self.lastTick.volume  # 当前K线内的成交量
            self.bar.volume += max(volumeChange, 0)  # 避免夜盘开盘lastTick.volume为昨日收盘数据，导致成交量变化为负的情况

        # 缓存Tick
        self.lastTick = tick

    def update_bar(self, bar):
        """
        Update 1 minute bar into generator
        window_bar更新, 5分钟 10分钟等
        功能就是:输入进来1分钟的Bar,合成5分钟或者15分钟之类的Bar
        改: 将update_bar变成完全的update_bar 分钟Bar 而将Update_bar里面的更新小时Bar提取出来,增加出来
        因为这里的逻辑,本身就是要输入的是小时线,才可以合成更多周期的小时线
        而且这里没有写K线的周期,很不方便
        1 正常情况下
        """
        # If not inited, create window bar object
        # 如果没有window_bar
        symb = re.sub(r'\d', '', bar.symbol).lower()
        dt = bar.datetime.replace(second=0, microsecond=0)
        if self.window == 3:
            period = INTERVAL_3M
            dt_start = bar.datetime.replace(minute=math.floor(dt.minute / 3) * 3)
            dt_end = dt_start + timedelta(minutes=3)
        elif self.window == 5:
            period = INTERVAL_5M
            dt_start = bar.datetime.replace(minute=math.floor(dt.minute / 5) * 5)
            dt_end = dt_start + timedelta(minutes=5)
        elif self.window == 15:
            period = INTERVAL_15M
            dt_start = bar.datetime.replace(minute=math.floor(dt.minute / 15) * 15)
            dt_end = dt_start + timedelta(minutes=15)
        elif self.window == 30:
            period = INTERVAL_30M
            dt_start = bar.datetime.replace(minute=math.floor(dt.minute / 30) * 30)
            dt_end = dt_start + timedelta(minutes=30)
            # 如果是商品期货,小时==10 分钟 == 0,30分钟线的终值为15
            if (symb in COMMODITY) and \
                    (bar.datetime.hour == 10) and \
                    (dt_start.minute == 0):
                dt_end = dt_end.replace(minute=15)
        elif self.window == 60:
            period = INTERVAL_60M
            dt_start = bar.datetime.replace(minute=0)
            dt_end = dt_start + timedelta(hours=1)
            if dt_start.hour == 11:
                dt_end = dt_end.replace(minute=30)

            elif (dt_start.hour == 13) and (symb in COMMODITY):
                dt_start = dt_start.replace(minute=30)

            elif (dt_start.hour == 23) and (symb in NIGHTGROUP_2330):
                dt_end = dt_end.replace(minute=30)

            elif (dt_start.hour == 2) and (symb in NIGHTGROUP_0230):
                dt_end = dt_end.replace(minute=30)

        if not self.window_bar:
            # Generate timestamp for bar data
            # 如果是分钟Bar,创建datetime
            # 创建Bar数据
            self.window_bar = VtBarData()

            self.window_bar.vtSymbol = bar.vtSymbol
            self.window_bar.symbol = bar.symbol
            self.window_bar.exchange = bar.exchange

            self.window_bar.open = bar.open
            self.window_bar.high = bar.high
            self.window_bar.low = bar.low

            self.window_bar.datetime = bar.datetime
            self.window_bar.tradedate = bar.tradedate
            self.window_bar.time = bar.time

            self.window_bar.datetime_start = dt_start
            self.window_bar.datetime_end =dt_end

            self.window_bar.openInterest = bar.openInterest
            self.window_bar.interval = period
        # Otherwise, update high/low price into window bar
        # 如果已经进行了初始化,
        else:
            # 这里加入新的合成逻辑，如果是不连续的bar,先推送
            # 如果有跳线的情况
            if bar.datetime >= self.window_bar.datetime_end:
                self.on_window_bar(self.window_bar)
                self.window_bar = None

                self.window_bar = VtBarData()

                self.window_bar.vtSymbol = bar.vtSymbol
                self.window_bar.symbol = bar.symbol
                self.window_bar.exchange = bar.exchange

                self.window_bar.open = bar.open
                self.window_bar.high = bar.high
                self.window_bar.low = bar.low

                self.window_bar.datetime = bar.datetime
                self.window_bar.tradedate = bar.tradedate
                self.window_bar.time = bar.time
                self.window_bar.datetime_start = dt_start
                self.window_bar.datetime_end = dt_end

                self.window_bar.openInterest = bar.openInterest
                self.window_bar.interval = period

            self.window_bar.high = max(
                self.window_bar.high, bar.high)
            self.window_bar.low_price = min(
                self.window_bar.low, bar.low)

        # Update close price/volume into window bar
        # 更新最新价,交易量
        self.window_bar.close = bar.close
        self.window_bar.volume += int(bar.volume)
        # self.window_bar.open_interest = bar.open_interest

        # Check if window bar completed
        # 先假定没有完成
        finished = False

        # x-minute bar
        # 如果是5分钟,则规则为: 4 + 1 整除5就推送,如果是15分钟,规则: 14 + 1 整除 15 推送
        # 如果是60分钟,则59 + 1 % 60 = 0, 其余不为0
        if not ((bar.datetime.minute + 1) % self.window):
            finished = True

        if finished:
            self.on_window_bar(self.window_bar)
            self.window_bar = None

        # Cache last bar object
        self.last_bar = bar

    def update_bar_hour(self, bar):
        """
        这里输入的是小时Bar,由小时K线生成多周期小时K线
        """
        # If not inited, create window bar object
        # 如果没有初始化

        symb = re.sub(r'\d', '', bar.symbol).lower()
        dt = bar.datetime.replace(minute=0, second=0, microsecond=0)
        if self.window == 2:
            period = INTERVAL_120M
            dt_start = bar.datetime.replace(hour=math.floor(dt.hour / 2) * 2)
            dt_end = dt_start + timedelta(hours=2)
        elif self.window == 4:
            period = INTERVAL_240M
            dt_start = bar.datetime.replace(hour=math.floor(dt.hour / 4) * 4)
            dt_end = dt_start + timedelta(hours=4)
        elif self.window == 6:
            period = INTERVAL_360M
            dt_start = bar.datetime.replace(hour=math.floor(dt.hour / 6) * 6)
            dt_end = dt_start + timedelta(hours=6)
        elif self.window == 24:
            period = INTERVAL_1D
            # 如果是商品期货
            if symb in COMMODITY:
                # 日盘品种
                if symb in DAYGROUP_1500:
                    dt_start = bar.datetime.replace(hour=9)
                    dt_end = bar.datetime.replace(hour=15)
                # 夜盘品种
                else:
                    # 如果输入的K线的星期小于5 并且是夜盘品种
                    if bar.datetime.weekday() < 4 and bar.datetime.hour > 20:
                        dt_start = bar.datetime.replace(hour=21)
                        dt_end = (dt_start + timedelta(hours=10)).replace(hour=15)
                    # 如果不连续的K线是盘品种,并且当前时间小于晚上8点,起始时间为昨天的21点
                    elif bar.datetime.weekday() < 4 and bar.datetime.hour < 20:
                        dt_start = (bar.datetime.replace(hour=0) - timedelta(hours=1)).replace(hour=21)
                        dt_end = bar.datetime.replace(hour=15)
                    # 周五晚上 夜盘品种
                    elif bar.datetime.weekday() == 4 and bar.datetime.hour > 20:
                        dt_start = bar.datetime.replace(hour=21)
                        dt_end = (dt_start + timedelta(days=3)).replace(hour=15)
                    # 周六凌晨 夜盘品种
                    elif bar.datetime.weekday() == 5 and bar.datetime.hour < 5:
                        dt_start = (bar.datetime.replace(hour=21) - timedelta(days=1))
                        dt_end = (dt_start + timedelta(days=3)).replace(hour=15)
                    # 周一
                    elif bar.datetime.weekday() == 0 and bar.datetime.hour < 15:
                        dt_start = (bar.datetime.replace(hour=21) - timedelta(days=3))
                        dt_end = (dt_start + timedelta(days=3)).replace(hour=15)

        if not self.window_bar:
            # Generate timestamp for bar data
            # 将数据变成整点数据

            self.window_bar = VtBarData()

            self.window_bar.vtSymbol = bar.vtSymbol
            self.window_bar.symbol = bar.symbol
            self.window_bar.exchange = bar.exchange

            self.window_bar.open = bar.open
            self.window_bar.high = bar.high
            self.window_bar.low = bar.low

            self.window_bar.datetime = bar.datetime
            self.window_bar.tradedate = bar.tradedate
            self.window_bar.time = bar.time

            self.window_bar.datetime_start = dt_start
            self.window_bar.datetime_end = dt_end

            self.window_bar.openInterest = bar.openInterest
            self.window_bar.interval = period

        # Otherwise, update high/low price into window bar
        # 如果有初始化,则进行高地价的更新
        else:
            if bar.datetime >= self.window_bar.datetime_end:
                self.on_window_bar(self.window_bar)
                self.window_bar = None

                self.window_bar = VtBarData()

                self.window_bar.vtSymbol = bar.vtSymbol
                self.window_bar.symbol = bar.symbol
                self.window_bar.exchange = bar.exchange

                self.window_bar.open = bar.open
                self.window_bar.high = bar.high
                self.window_bar.low = bar.low

                self.window_bar.datetime = bar.datetime
                self.window_bar.tradedate = bar.tradedate
                self.window_bar.time = bar.time

                self.window_bar.datetime_start = dt_start
                self.window_bar.datetime_end = dt_end

                self.window_bar.openInterest = bar.openInterest
                self.window_bar.interval = period

        # Update close price/volume into window bar
        # 更新最新价,交易量
        self.window_bar.high = max(self.window_bar.high, bar.high)
        self.window_bar.low = min(self.window_bar.low, bar.low)
        self.window_bar.close = bar.close
        self.window_bar.volume += int(bar.volume)
        # self.window_bar.open_interest = bar.open_interest

        # X小时已经走完
        if (bar.datetime.hour + 1) == bar.datetime_end.hour:  # 可以用X整除
            # 生成上一X分钟K线的时间戳
            # 推送
            self.on_window_bar(self.window_bar)
            # 清空老K线缓存对象
            self.window_bar = None

        self.last_bar = bar

    def generate(self):
        """
        Generate the bar data and call callback immediately.
        强制合成由tick合成的一分钟线,在尾盘的时候用到
        """
        self.bar.datetime = self.bar.datetime.replace(
            second=0, microsecond=0
        )
        self.on_bar(self.bar)
        self.bar = None


########################################################################
class ArrayManager(object):
    """
    K线序列管理工具，负责：
    1. K线时间序列的维护
    2. 常用技术指标的计算
    """

    #----------------------------------------------------------------------
    def __init__(self, size=100):
        """Constructor"""
        self.count = 0                      # 缓存计数
        self.size = size                    # 缓存大小
        self.inited = False                 # True if count>=size

        self.timeArray = []
        self.openArray = []
        self.highArray = []
        self.lowArray = []
        self.closeArray = []
        self.volumeArray = []
        """
        self.openArray = np.zeros(size)     # OHLC
        self.highArray = np.zeros(size)
        self.lowArray = np.zeros(size)
        self.closeArray = np.zeros(size)
        self.volumeArray = np.zeros(size)
        """
        
    #----------------------------------------------------------------------
    def updateBar(self, bar):
        """更新K线"""
        self.count += 1
        #if not self.inited and self.count >= self.size:
        if not self.inited and self.count >= self.size:
            self.inited = True

        # self.timeArray[:-1] = self.timeArray[1:]
        # self.openArray[:-1] = self.openArray[1:]
        # self.highArray[:-1] = self.highArray[1:]
        # self.lowArray[:-1] = self.lowArray[1:]
        # self.closeArray[:-1] = self.closeArray[1:]
        # self.volumeArray[:-1] = self.volumeArray[1:]

        self.timeArray.append(bar.datetime.strftime("%Y-%m-%d %H:%M:%S"))
        self.openArray.append(bar.open)
        self.highArray.append(bar.high)
        self.lowArray.append(bar.low)
        self.closeArray.append(bar.close)
        self.volumeArray.append(bar.volume)
        """
        self.openArray[-1] = bar.open
        self.highArray[-1] = bar.high
        self.lowArray[-1] = bar.low        
        self.closeArray[-1] = bar.close
        self.volumeArray[-1] = bar.volume
        """
    # ----------------------------------------------------------------------
    @property
    def time(self):
        """获取时间序列"""
        return self.timeArray

    #----------------------------------------------------------------------
    @property
    def open(self):
        """获取开盘价序列"""
        return np.array(self.openArray)
        
    #----------------------------------------------------------------------
    @property
    def high(self):
        """获取最高价序列"""
        return np.array(self.highArray)
    
    #----------------------------------------------------------------------
    @property
    def low(self):
        """获取最低价序列"""
        return np.array(self.lowArray)
    
    #----------------------------------------------------------------------
    @property
    def close(self):
        """获取收盘价序列"""
        return np.array(self.closeArray)
    
    #----------------------------------------------------------------------
    @property    
    def volume(self):
        """获取成交量序列"""
        return self.volumeArray
    
    #----------------------------------------------------------------------
    def sma(self, n, array=False):
        """简单均线"""
        result = talib.SMA(self.close, n)
        if array:
            return result
        return result[-1]

    #----------------------------------------------------------------------
    def ema(self, n, array=False):
        """指数平均数指标"""
        result = talib.EMA(self.close, n)
        if array:
            return result
        return result[-1]
    
    #----------------------------------------------------------------------
    def std(self, n, array=False):
        """标准差"""
        result = talib.STDDEV(self.close, n)
        if array:
            return result
        return result[-1]
    
    #----------------------------------------------------------------------
    def cci(self, n, array=False):
        """CCI指标"""
        result = talib.CCI(self.high, self.low, self.close, n)
        if array:
            return result
        return result[-1]
        
    #----------------------------------------------------------------------
    def atr(self, n, array=False):
        """ATR指标"""
        result = talib.ATR(self.high, self.low, self.close, n)
        if array:
            return result
        return result[-1]
        
    #----------------------------------------------------------------------
    def rsi(self, n, array=False):
        """RSI指标"""
        result = talib.RSI(self.close, n)
        if array:
            return result
        return result[-1]
    
    #----------------------------------------------------------------------
    def macd(self, fastPeriod, slowPeriod, signalPeriod, array=False):
        """MACD指标"""
        macd, signal, hist = talib.MACD(self.close, fastPeriod,
                                        slowPeriod, signalPeriod)
        if array:
            return macd, signal, hist
        return macd[-1], signal[-1], hist[-1]
    
    #----------------------------------------------------------------------
    def adx(self, n, array=False):
        """ADX指标"""
        result = talib.ADX(self.high, self.low, self.close, n)
        if array:
            return result
        return result[-1]
    
    #----------------------------------------------------------------------
    def boll(self, n, dev, array=False):
        """布林通道"""
        mid = self.sma(n, array)
        std = self.std(n, array)
        
        up = mid + std * dev
        down = mid - std * dev
        
        return up, down    
    
    #----------------------------------------------------------------------
    def keltner(self, n, dev, array=False):
        """肯特纳通道"""
        mid = self.sma(n, array)
        atr = self.atr(n, array)
        
        up = mid + atr * dev
        down = mid - atr * dev
        
        return up, down
    
    #----------------------------------------------------------------------
    def donchian(self, n, array=False):
        """唐奇安通道"""
        up = talib.MAX(self.high, n)
        down = talib.MIN(self.low, n)
        
        if array:
            return up, down
        return up[-1], down[-1]




# 数字货币时间处理，处理本地时间与ISO时间
def timeStartEnd(time, interval):

    # 这里暂时先简化处理，按正常时间处理即可
    # 先处理tradeday交易日期的问题
    tradeday = time.strftime("%Y-%m-%d")

    if interval == INTERVAL_5M:
        minstart = math.floor(time.minute / 5) * 5
        timestart = time.replace(minute=minstart)
        timeend = timestart + timedelta(minutes=5, seconds=0)
        return timestart, timeend, tradeday
    elif interval == INTERVAL_15M:
        minstart = math.floor(time.minute / 15) * 15
        timestart = time.replace(minute=minstart)
        timeend = timestart + timedelta(minutes=15, seconds=0)
        return timestart, timeend, tradeday
    elif interval == INTERVAL_30M:
        minstart = math.floor(time.minute / 30) * 30
        timestart = time.replace(minute=minstart)
        timeend = timestart + timedelta(minutes=30, seconds=0)
        return timestart, timeend, tradeday
        # 60分钟这里
    elif interval == INTERVAL_60M:
        timestart = time.replace(minute=0)
        timeend = timestart + timedelta(hours=1)
        return timestart, timeend, tradeday
    elif interval == INTERVAL_1D:
        # 日线这里
        timestart = time.replace(hour=0)
        timeend = timestart + timedelta(days=1)
        return timestart, timeend, tradeday
    else:
        timestart = None
        timeend = None

        print('输入的时间周期有误，请重新输入')


    return timestart, timeend, tradeday
