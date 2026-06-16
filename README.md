# DSN-exp

-> 本文件不是文档，文档往这看：[![zread](https://img.shields.io/badge/Ask_Zread-_.svg?style=flat&color=00b0aa&labelColor=000000&logo=data%3Aimage%2Fsvg%2Bxml%3Bbase64%2CPHN2ZyB3aWR0aD0iMTYiIGhlaWdodD0iMTYiIHZpZXdCb3g9IjAgMCAxNiAxNiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHBhdGggZD0iTTQuOTYxNTYgMS42MDAxSDIuMjQxNTZDMS44ODgxIDEuNjAwMSAxLjYwMTU2IDEuODg2NjQgMS42MDE1NiAyLjI0MDFWNC45NjAxQzEuNjAxNTYgNS4zMTM1NiAxLjg4ODEgNS42MDAxIDIuMjQxNTYgNS42MDAxSDQuOTYxNTZDNS4zMTUwMiA1LjYwMDEgNS42MDE1NiA1LjMxMzU2IDUuNjAxNTYgNC45NjAxVjIuMjQwMUM1LjYwMTU2IDEuODg2NjQgNS4zMTUwMiAxLjYwMDEgNC45NjE1NiAxLjYwMDFaIiBmaWxsPSIjZmZmIi8%2BCjxwYXRoIGQ9Ik00Ljk2MTU2IDEwLjM5OTlIMi4yNDE1NkMxLjg4ODEgMTAuMzk5OSAxLjYwMTU2IDEwLjY4NjQgMS42MDE1NiAxMS4wMzk5VjEzLjc1OTlDMS42MDE1NiAxNC4xMTM0IDEuODg4MSAxNC4zOTk5IDIuMjQxNTYgMTQuMzk5OUg0Ljk2MTU2QzUuMzE1MDIgMTQuMzk5OSA1LjYwMTU2IDE0LjExMzQgNS42MDE1NiAxMy43NTk5VjExLjAzOTlDNS42MDE1NiAxMC42ODY0IDUuMzE1MDIgMTAuMzk5OSA0Ljk2MTU2IDEwLjM5OTlaIiBmaWxsPSIjZmZmIi8%2BCjxwYXRoIGQ9Ik0xMy43NTg0IDEuNjAwMUgxMS4wMzg0QzEwLjY4NSAxLjYwMDEgMTAuMzk4NCAxLjg4NjY0IDEwLjM5ODQgMi4yNDAxVjQuOTYwMUMxMC4zOTg0IDUuMzEzNTYgMTAuNjg1IDUuNjAwMSAxMS4wMzg0IDUuNjAwMUgxMy43NTg0QzE0LjExMTkgNS42MDAxIDE0LjM5ODQgNS4zMTM1NiAxNC4zOTg0IDQuOTYwMVYyLjI0MDFDMTQuMzk4NCAxLjg4NjY0IDE0LjExMTkgMS42MDAxIDEzLjc1ODQgMS42MDAxWiIgZmlsbD0iI2ZmZiIvPgo8cGF0aCBkPSJNNCAxMkwxMiA0TDQgMTJaIiBmaWxsPSIjZmZmIi8%2BCjxwYXRoIGQ9Ik00IDEyTDEyIDQiIHN0cm9rZT0iI2ZmZiIgc3Ryb2tlLXdpZHRoPSIxLjUiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIvPgo8L3N2Zz4K&logoColor=ffffff)](https://zread.ai/ccjjfdyqlhy/DSN-exp)  
-> 代码库复杂度分析往这看：[**屎山代码分析报告**](https://github.com/ccjjfdyqlhy/DSN-exp/blob/main/REPORT.md)  

所以，我最近在干嘛？

**本次更新：后端第21条**

Concepts
---
- 剧本系统：两端皆可使用，起到引导用户/做游戏的作用（？  
- ~~写个技能接入ncm！！~~  
- ~~从ncm技能的歌词蒸馏人格特点~~  
- 环境全模态感知协议接口（转后端13、20、21）  
- 开发提交前钩子——屎山分析、编年史添加、README更新，自动化。  
- 更大更强的记忆系统！（转后端7、19、28、32）

后端
---
~~0、优化响应速度：并行推理、分段传输响应~~  
~~1、复活本地lms，完善请求接口全部适应，拓宽协议支持传输图片~~  
~~2、使用本地lms作为主模型的模态转换模型~~  
~~3、融合engine到app~~（虽然现在app代码量还是比较多的，但是复用了不少）   
4、剧本系统01：给AI写的脚本以及ooc检测  
5、接入IM！  
~~6、后端API集线器收集更多模型信息，比如消耗Tokens~~  
7、话题管理系统、多层提示词系统  
~~8、PersonalitySystemV3、印象系统新版本：更加主动，基于随机种子生成人格模型，允许自定义人格方向。角色卡。~~  
~~9、数据库加密。~~  
10、优化世界叙述现实系统：提示词重写、种子生成世界什么的。  
11、**实用性增强**，用作Vibe coding client。  
~~12、基于AI的TTS文本预处理，输出极为TTS友好的文本。还要特别生动！~~  
13、动态视觉：环境感知协议Part1（挖，那是诱人的  
~~14、复活叙事世界感知系统：修复记忆不注入~~  
~~15、计费账单系统。~~  
~~16、完善语音交互逻辑~~  
~~17、**修复记忆系统BUG**，重写记忆模型提示词。~~  
~~18、**修复Agent循环中技能系统BUG**~~  
19、话题系统和记忆系统的整合。  
20、设备管理器核心：和环境感知协议整合——旨在让系统控制多台计算机。  
~~21、连续对话模式：语音感知通话。~~  
~~22、人格蒸馏系统完善~~  
~~23、待机功能：掌握用户的请求节律，用户不用的时候待机，进行记忆整理、人格蒸馏、声音克隆什么的长期任务。~~  
24、增强视觉：自动区分、处理、格式化文档  
25、图书馆：存放个人UGC，闲置的时候读一读，加深了解。  
~~26、内置GitHub技能。~~  
~~27、优化处理效率（第一波）~~  
28、检查并修复记忆系统的提示词丢失问题。  
~~29、优化性格抽取模型的异步流程。（第二波）~~  
30、解决异步调用返回仍然需要F5的问题（你怎么又回来了）  
~~31、支持并行/串行推理TTS，以及对应的profile handling~~  
32、升级记忆系统为向量数据库检索。  
~~33、角色卡从数据库独立，后者仅仅保存人格状态。~~  
34、丰富熟悉度、亲密度驱动的语言风格变化。  
35、根据DeepSeek官方文档，提供更可控的主模型生成。  
36、人格蒸馏系统BUG大修、彻底独立于数据库，性格提取修复  

前端
---
~~1、支持LanaPixel字体的Markdown渲染。支持换行。~~  
2、实时显示插件状态：EMO ^/v 0.x MEM () 21%   
3、F5前/后显示内容对齐。  
~~4、滚动判定（更新）~~  
~~5、回复计时计价，融合token_calc.py~~  
6、左右面板开拓：可以让插件能自定义显示一些面板  
~~7、底栏：DSN-exp V4-API [Alt] 查看键位 XX:XX~~  
~~8、键位说明，游戏风格。~~  
~~9、打字机效果语气增强。~~  

仓库维生系统
---
1、实现无AI部分：提交前运行脚本文件`run_before_sub.py`，自动执行代码复杂度检查，生成报告。  
2、实现有AI部分：这个脚本还会调用本地模型总结本次修改的改动位点，自动填充Commit message，然后让模型续写项目编年史，记录开发历程。