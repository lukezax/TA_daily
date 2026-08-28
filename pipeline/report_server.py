"""
报告 HTTP 服务
提供局域网 HTTP 访问，展示历史报告列表和单日报告
"""

import logging
from pathlib import Path

from flask import Flask, send_from_directory, abort

from pipeline.config import PipelineConfig

logger = logging.getLogger(__name__)


def create_app(config: PipelineConfig) -> Flask:
    """创建 Flask 应用"""
    report_dir = Path(config.report_output_dir)
    report_dir.mkdir(parents=True, exist_ok=True)

    app = Flask(__name__, static_folder=None)

    @app.route("/")
    def index():
        """报告列表页"""
        index_file = report_dir / "index.html"
        if index_file.exists():
            return index_file.read_text(encoding="utf-8")
        return "<h1>暂无报告</h1><p>尚未生成任何筛选报告。</p>", 200

    @app.route("/report/<date>")
    def report(date):
        """单日报告页面"""
        report_file = report_dir / f"{date}.html"
        if report_file.exists():
            return report_file.read_text(encoding="utf-8")
        # 兼容不带 .html 后缀的访问
        abort(404)

    @app.route("/<date>.html")
    def report_html(date):
        """单日报告页面（直接文件名访问）"""
        report_file = report_dir / f"{date}.html"
        if report_file.exists():
            return report_file.read_text(encoding="utf-8")
        abort(404)

    @app.route("/static/<path:filename>")
    def static_files(filename):
        """静态资源"""
        return send_from_directory(str(report_dir / "static"), filename)

    return app


class ReportServer:
    """轻量 HTTP 报告服务"""

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.port = config.server_port
        self.app = create_app(config)

    def start(self):
        """启动 HTTP 服务（阻塞）"""
        logger.info("报告服务启动: http://0.0.0.0:%d", self.port)
        self.app.run(host="0.0.0.0", port=self.port, debug=False)
