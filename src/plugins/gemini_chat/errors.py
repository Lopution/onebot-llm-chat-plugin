# Gemini API 异常类
"""
定义 Gemini API 相关的异常类型。

异常层次：
- GeminiAPIError (基类)
  - RateLimitError (429 限流)
  - AuthenticationError (401/403 认证失败)
  - ServerError (5xx 服务端错误)
"""


class GeminiAPIError(Exception):
    """Gemini API 异常基类
    
    Attributes:
        message: 错误消息
        status_code: HTTP 状态码
        retry_after: 建议重试等待时间（秒）
    """
    def __init__(self, message: str, status_code: int = 0, retry_after: int = 0):
        self.message = message
        self.status_code = status_code
        self.retry_after = retry_after
        super().__init__(message)


class RateLimitError(GeminiAPIError):
    """429 限流错误
    
    当 API 调用频率超过限制时抛出。
    retry_after 属性包含建议的等待时间。
    """
    pass


class AuthenticationError(GeminiAPIError):
    """401/403 认证错误
    
    当 API Key 无效或权限不足时抛出。
    """
    pass


class ServerError(GeminiAPIError):
    """5xx 服务端错误
    
    当 API 服务器出现内部错误时抛出。
    通常可以通过重试解决。
    """
    pass
