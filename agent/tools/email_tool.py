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
Email 发送工具模块
"""
import os
import json
import smtplib
from typing import List, Optional
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from email.header import Header
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class EmailInput(BaseModel):
    to: List[str] = Field(description="收件人邮箱地址列表")
    cc: Optional[List[str]] = Field(default=None, description="抄送人邮箱地址列表（可选）")
    bcc: Optional[List[str]] = Field(default=None, description="密送人邮箱地址列表（可选）")
    subject: str = Field(description="邮件标题")
    body: str = Field(description="邮件正文")
    is_html: Optional[bool] = Field(default=False, description="邮件正文是否为HTML格式（可选，默认False）")
    attachments: Optional[List[str]] = Field(default=None, description="附件文件路径列表（可选）")


class EmailTool(BaseTool):
    """
    Email 发送工具
    """

    name: str = "send_email"
    description: str = "发送邮件，支持收件人、抄送、密送、标题、正文和附件"
    args_schema: type[BaseModel] = EmailInput
    
    # 配置信息
    smtp_server: str = ""
    encryption: str = "SSL"  # 无、SSL、TLS
    smtp_port: int = 465
    smtp_username: str = ""
    smtp_password: str = ""
    from_name: str = ""  # 发件人显示名称

    def _run(
        self,
        to: List[str] = None,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        subject: str = "",
        body: str = "",
        is_html: bool = False,
        attachments: Optional[List[str]] = None,
        **kwargs
    ) -> str:
        """发送邮件"""
        # 支持传入参数字符串的情况
        if isinstance(to, str) and not subject and '{' in to:
            try:
                params = json.loads(to)
                to = params.get("to", [])
                cc = params.get("cc")
                bcc = params.get("bcc")
                subject = params.get("subject", "")
                body = params.get("body", "")
                is_html = params.get("is_html", False)
                attachments = params.get("attachments")
            except json.JSONDecodeError:
                pass

        # 从 kwargs 中获取参数
        if not to and 'to' in kwargs:
            to = kwargs['to']
        if not cc and 'cc' in kwargs:
            cc = kwargs['cc']
        if not bcc and 'bcc' in kwargs:
            bcc = kwargs['bcc']
        if not subject and 'subject' in kwargs:
            subject = kwargs['subject']
        if not body and 'body' in kwargs:
            body = kwargs['body']
        if 'is_html' in kwargs:
            is_html = kwargs['is_html']
        if not attachments and 'attachments' in kwargs:
            attachments = kwargs['attachments']

        # 验证必填参数
        if not to:
            return "错误: 收件人列表不能为空"
        if not subject:
            return "错误: 邮件标题不能为空"
        if not body:
            return "错误: 邮件正文不能为空"
        if not self.smtp_server:
            return "错误: SMTP 服务器地址未配置"
        if not self.smtp_username:
            return "错误: SMTP 用户名未配置"
        if not self.smtp_password:
            return "错误: SMTP 密码未配置"

        # 确保 to 是列表
        if isinstance(to, str):
            to = [to]
        if isinstance(cc, str):
            cc = [cc]
        if isinstance(bcc, str):
            bcc = [bcc]
        if isinstance(attachments, str):
            attachments = [attachments]

        try:
            # 创建邮件对象
            msg = MIMEMultipart()
            # 设置发件人，如果配置了 from_name，则使用格式 "名称 <邮箱>"
            if self.from_name:
                # 使用 Header 正确编码中文字符
                from_header = Header(self.from_name, 'utf-8')
                from_header.append(f' <{self.smtp_username}>', 'ascii')
                msg['From'] = from_header
            else:
                msg['From'] = self.smtp_username
            msg['To'] = ', '.join(to)
            if cc:
                msg['Cc'] = ', '.join(cc)
            msg['Subject'] = subject

            # 添加正文
            msg.attach(MIMEText(body, 'html' if is_html else 'plain', 'utf-8'))

            # 添加附件
            if attachments:
                for attachment_path in attachments:
                    if not os.path.exists(attachment_path):
                        continue
                    
                    with open(attachment_path, "rb") as attachment:
                        part = MIMEBase('application', 'octet-stream')
                        part.set_payload(attachment.read())
                    
                    encoders.encode_base64(part)
                    part.add_header(
                        'Content-Disposition',
                        f'attachment; filename= {os.path.basename(attachment_path)}'
                    )
                    msg.attach(part)

            # 连接 SMTP 服务器并发送
            all_recipients = to.copy()
            if cc:
                all_recipients.extend(cc)
            if bcc:
                all_recipients.extend(bcc)

            if self.encryption == "SSL":
                server = smtplib.SMTP_SSL(self.smtp_server, self.smtp_port)
            elif self.encryption == "TLS":
                server = smtplib.SMTP(self.smtp_server, self.smtp_port)
                server.starttls()
            else:
                server = smtplib.SMTP(self.smtp_server, self.smtp_port)

            server.login(self.smtp_username, self.smtp_password)
            text = msg.as_string()
            server.sendmail(self.smtp_username, all_recipients, text)
            server.quit()

            return f"邮件发送成功！收件人: {', '.join(to)}"

        except Exception as e:
            return f"邮件发送失败: {str(e)}"


def create_email_tool(smtp_server: str, smtp_encryption: str, smtp_port: int, smtp_usename: str, smtp_password: str,
                      from_name: str) -> EmailTool:
    """
    创建 Email 工具
    """
    tool = EmailTool()
    tool.smtp_server = smtp_server
    tool.encryption = smtp_encryption
    tool.smtp_port = smtp_port
    tool.smtp_username = smtp_usename
    tool.smtp_password = smtp_password
    tool.from_name = from_name
    return tool
