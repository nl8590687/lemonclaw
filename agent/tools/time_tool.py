# Copyright 2026 LemonClaw Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
获取当前时间的工具，包含公历、农历、节气和节日信息
"""

import datetime
import math

from langchain_core.tools import tool
import ephem
from zhdate import ZhDate

lunar_years = [
    "甲子", "乙丑", "丙寅", "丁卯", "戊辰", "己巳",
    "庚午", "辛未", "壬申", "癸酉", "甲戌", "乙亥",
    "丙子", "丁丑", "戊寅", "己卯", "庚辰", "辛巳",
    "壬午", "癸未", "甲申", "乙酉", "丙戌", "丁亥",
    "戊子", "己丑", "庚寅", "辛卯", "壬辰", "癸巳",
    "甲午", "乙未", "丙申", "丁酉", "戊戌", "己亥",
    "庚子", "辛丑", "壬寅", "癸卯", "甲辰", "乙巳",
    "丙午", "丁未", "戊申", "己酉", "庚戌", "辛亥",
    "壬子", "癸丑", "甲寅", "乙卯", "丙辰", "丁巳",
    "戊午", "己未", "庚申", "辛酉", "壬戌", "癸亥",
]

lunar_months = ["正月", "二月", "三月", "四月", "五月", "六月",
                "七月", "八月", "九月", "十月", "十一月", "腊月"]

lunar_days = ["初一", "初二", "初三", "初四", "初五", "初六", "初七", "初八", "初九", "初十",
              "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八", "十九", "二十",
              "廿一", "廿二", "廿三", "廿四", "廿五", "廿六", "廿七", "廿八", "廿九", "三十"]

# 24节气
jieqi=["春分","清明","谷雨","立夏","小满","芒种",\
       "夏至","小暑","大暑","立秋","处暑","白露",\
       "秋分","寒露","霜降","立冬","小雪","大雪",\
       "冬至","小寒","大寒","立春","雨水","惊蛰"]


def _get_lunar_date(year: int, month: int, day: int) -> dict:
    """获取农历日期"""
    lunar_date = ZhDate.from_datetime(datetime.datetime(year, month, day))
    return {
        "lunar_year": lunar_years[(lunar_date.lunar_year-1984) % 60],
        "lunar_month": lunar_months[lunar_date.lunar_month - 1],
        "lunar_day": lunar_days[lunar_date.lunar_day - 1],
    }


def ecliptic_lon(jd_utc):
    """
    计算黄经

    :param jd_utc: UTC日期时间
    :return: 黄纬
    """
    # 构造太阳
    s = ephem.Sun(jd_utc)
    # 求太阳的视赤经视赤纬（epoch设为所求时间就是视赤经视赤纬）
    equ = ephem.Equatorial(s.ra, s.dec, epoch=jd_utc)
    # 赤经赤纬转到黄经黄纬
    e = ephem.Ecliptic(equ)
    # 返回黄纬
    return e.lon


def sta(jd):
    """
    根据时间求太阳黄经，计算到了第几个节气，春分序号为0

    :param jd:
    :return:
    """
    e = ecliptic_lon(jd)
    n = int(e * 180.0 / math.pi / 15)
    return n


def iteration(jd, sta):
    """
    根据当前时间，求下个节气的发生时间

    :param jd: 要求的开始时间
    :param sta: 不同的状态函数
    :return:
    """
    # 初始状态(太阳处于什么位置)
    s1 = sta(jd)
    s0 = s1
    # 初始时间改变量设为1天
    dt = 1.0
    while True:
        jd += dt
        s = sta(jd)
        if s0 != s:
            s0 = s
            dt = - dt / 2#使时间改变量折半减小
        if abs(dt) < 0.0000001 and s != s1:
            break
    return jd


def calculate_solar_term(year: int, month: int, day: int) -> str:
    """
    获取节气

    :param year:
    :param month:
    :param day:
    :return:
    """
    # 获取当前时间的一个儒略日和1899/12/31 12:00:00儒略日的差值
    jd: datetime.datetime = ephem.Date(datetime.datetime(year, month, day, 0, 0, 0, 0))
    e = ecliptic_lon(jd)
    n = int(e * 180.0 / math.pi / 15) + 1

    # 从当前时间开始计算下一个节气的时间
    jd = iteration(jd, sta)
    d = ephem.Date(jd + 1 / 3).tuple()
    if d[0] == year and d[1] == month and d[2] == day:
        return "{0} {1:02d}:{2:02d}:{3:03.1f}".format(jieqi[n], d[3], d[4], d[5])
    else:
        return "无节气"


def _get_festivals(year: int, month: int, day: int, lunar_info: dict) -> list:
    """
    获取节日信息
    """
    festivals = []

    solar_festivals = {
        (1, 1): "元旦", (2, 14): "情人节", (3, 8): "妇女节",
        (3, 12): "植树节", (4, 1): "愚人节", (5, 1): "国际劳动节",
        (5, 4): "青年节", (6, 1): "儿童节", (7, 1): "建党节",
        (8, 1): "建军节", (9, 10): "教师节", (10, 1): "国庆节",
        (12, 25): "圣诞节"
    }

    if (month, day) in solar_festivals:
        festivals.append(solar_festivals[(month, day)])

    lunar_festivals = {
        ("正月", "初一"): "春节", ("正月", "十五"): "元宵节",
        ("五月", "初五"): "端午节", ("八月", "十五"): "中秋节",
        ("九月", "初九"): "重阳节", ("腊月", "三十"): "除夕",
        ("腊月", "初八"): "腊八节"
    }

    if (lunar_info["lunar_month"], lunar_info["lunar_day"]) in lunar_festivals:
        festivals.append(lunar_festivals[(lunar_info["lunar_month"], lunar_info["lunar_day"])])

    return festivals


@tool
def get_current_time() -> str:
    """
    获取当前时间，包含公历日期、星期、农历日期、节气和公共节日信息
    """
    try:
        now = datetime.datetime.now()
        year, month, day = now.year, now.month, now.day
        weekday = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][now.weekday()]
        formatted_time = now.strftime("%Y-%m-%d %H:%M:%S")

        lunar_info = _get_lunar_date(year, month, day)
        solar_term = calculate_solar_term(year, month, day)
        festivals = _get_festivals(year, month, day, lunar_info)

        result = (
            f"当前时间: {formatted_time}\n"
            f"公历: {year}年{month}月{day}日 {weekday}\n"
            f"农历: {lunar_info['lunar_year']}年 {lunar_info['lunar_month']} {lunar_info['lunar_day']}"
        )
        if solar_term:
            result += f"\n节气: {solar_term}"
        if festivals:
            result += f"\n节日: {', '.join(festivals)}"

        return result
    except Exception as e:
        return f"获取时间失败：{str(e)}"


def create_time_tool():
    """
    创建时间工具
    """
    return get_current_time
