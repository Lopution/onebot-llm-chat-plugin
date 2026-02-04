#!/bin/bash
# Mika Bot 文档构建脚本
# 用于安装文档依赖并构建 API 文档

set -e

echo "📚 Mika Bot 文档构建脚本"
echo "========================"

# 切换到项目根目录
cd "$(dirname "$0")/.."

# 安装文档依赖
echo "📦 安装文档依赖..."
pip install -e ".[docs]"

# 构建文档
echo "🔨 构建文档..."
mkdocs build

echo "✅ 文档构建完成！"
echo "📁 输出目录: site/"
echo ""
echo "💡 提示: 运行 'mkdocs serve' 可在本地预览文档"
