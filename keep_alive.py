from http.server import BaseHTTPRequestHandler
import asyncio
import sys
import os
import json
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sla_bot import SLABot

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        
        async def run_bot():
            bot = SLABot()
            await bot.check_tasks()
            return {
                "status": "ok", 
                "message": "Tasks checked",
                "time": datetime.now().isoformat()
            }
        
        result = asyncio.run(run_bot())
        self.wfile.write(json.dumps(result).encode())
        return
