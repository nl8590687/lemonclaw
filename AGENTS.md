This file provides guidance to AI coding agents working with this repository.

## Project Overview
LemonClaw is an open-source, universal AI digital employee agent.

## Project Structure

```
|- .lemonclaw/    LemonClaw核心配置存储目录
|--- .env         LemonClaw环境变量配置文件
|--- .env.example LemonClaw环境变量配置文件样例文件
|--- lemonclaw.db LemonClaw全局Sqlite3数据库文件
|- agent/         Agent实现模块
|- channels/      输入输出设备和通道实现模块
|- dao/           数据库model和dao操作模块
|- config/        配置相关代码模块
|- tests/         单元测试目录
|- loop.py        Agent Loop核心代码
|- main.py        启动入口代码
```

## Structure Design

## 约束
1. 实现代码之前，必须先了解当前项目的整体代码风格和架构设计，保持现在的设计不变 
2. 整个项目全局只能使用一个 sqlite数据库文件`.lemonclaw/lemonclaw.db`，不允许出现多个。
