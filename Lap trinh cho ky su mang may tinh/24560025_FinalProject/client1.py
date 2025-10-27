# client1.py - PyQt5 GUI Client with Room Management
import sys
import socket
import json
import os
import struct
import logging
from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout,
                            QWidget, QPushButton, QTextEdit, QLabel, QLineEdit,
                            QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
                            QFileDialog, QMessageBox, QTabWidget, QInputDialog,
                            QComboBox, QSplitter, QProgressBar, QStatusBar, QFrame)
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QTimer, QMutex
from PyQt5.QtGui import QFont, QIcon, QPalette, QColor
import uuid

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ClientThread(QThread):
    log_message = pyqtSignal(str)
    connection_status_changed = pyqtSignal(bool, str)
    room_list_updated = pyqtSignal(list)
    file_list_updated = pyqtSignal(list)
    room_joined = pyqtSignal(str, str)  # room_id, room_name
    upload_progress = pyqtSignal(int)  # progress percentage
    download_progress = pyqtSignal(int)  # progress percentage
    room_updated = pyqtSignal(str, str, int)  # room_id, room_name, member_count
    
    def __init__(self, host='localhost', port=8888):
        super().__init__()
        self.host = host
        self.port = port
        self.socket = None
        self.running = False
        self.current_room_id = None
        self.current_room_name = None
        self.username = "Anonymous"
        self.mutex = QMutex()
        self.auto_reconnect = True
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        self.connected = False
    
    def set_username(self, username):
        """Set the client username"""
        self.username = username
    
    def connect_to_server(self):
        """Connect to the server with retry logic"""
        try:
            if self.socket:
                try:
                    self.socket.close()
                except:
                    pass
                self.socket = None
            
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(10.0)
            self.socket.connect((self.host, self.port))
            self.running = True
            self.connected = True
            self.reconnect_attempts = 0
            
            self.connection_status_changed.emit(True, f"Connected to {self.host}:{self.port}")
            self.log_message.emit("Connected to server")
            logger.info(f"Connected to server {self.host}:{self.port}")
            return True
            
        except Exception as e:
            self.connected = False
            self.connection_status_changed.emit(False, f"Connection failed: {e}")
            self.log_message.emit(f"Connection failed: {e}")
            logger.error(f"Connection failed: {e}")
            return False
    
    def disconnect_from_server(self):
        """Disconnect from server"""
        self.running = False
        self.connected = False
        self.auto_reconnect = False
        
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None
        
        self.current_room_id = None
        self.current_room_name = None
        self.connection_status_changed.emit(False, "Disconnected")
        self.log_message.emit("Disconnected from server")
    
    def send_request(self, request):
        """Send JSON request to server with error handling"""
        if not self.socket or not self.running or not self.connected:
            return False
        
        self.mutex.lock()
        try:
            request_data = json.dumps(request).encode('utf-8')
            length_data = struct.pack('!I', len(request_data))
            self.socket.send(length_data + request_data)
            return True
        except Exception as e:
            self.log_message.emit(f"Error sending request: {e}")
            logger.error(f"Error sending request: {e}")
            self.connected = False
            return False
        finally:
            self.mutex.unlock()
    
    def receive_response(self, timeout=30):
        """Receive JSON response from server with timeout"""
        try:
            if not self.socket or not self.connected:
                return None
            
            self.socket.settimeout(timeout)
            length_data = self.socket.recv(4)
            if not length_data:
                self.connected = False
                return None
            
            length = struct.unpack('!I', length_data)[0]
            
            if length > 10 * 1024 * 1024:  # 10MB limit
                return None
            
            data = b''
            while len(data) < length:
                chunk = self.socket.recv(min(8192, length - len(data)))
                if not chunk:
                    self.connected = False
                    return None
                data += chunk
            
            return json.loads(data.decode('utf-8'))
            
        except socket.timeout:
            self.log_message.emit("Server response timeout")
            return None
        except Exception as e:
            self.log_message.emit(f"Error receiving response: {e}")
            logger.error(f"Error receiving response: {e}")
            self.connected = False
            return None
    
    def receive_file_data(self, file_path, file_size):
        """Receive file data from server with progress"""
        try:
            with open(file_path, 'wb') as f:
                received = 0
                while received < file_size:
                    chunk_size = min(8192, file_size - received)
                    chunk = self.socket.recv(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    received += len(chunk)
                    
                    progress = int((received / file_size) * 100)
                    self.download_progress.emit(progress)
            
            return received == file_size
        except Exception as e:
            self.log_message.emit(f"Error receiving file: {e}")
            return False
    
    def send_file_data(self, file_path):
        """Send file data to server with progress"""
        try:
            file_size = os.path.getsize(file_path)
            sent = 0
            
            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(8192)
                    if not chunk:
                        break
                    self.socket.send(chunk)
                    sent += len(chunk)
                    
                    progress = int((sent / file_size) * 100)
                    self.upload_progress.emit(progress)
            
            return True
        except Exception as e:
            self.log_message.emit(f"Error sending file: {e}")
            return False
    
    def create_room(self, room_name):
        """Create a new room"""
        try:
            request = {
                'command': 'create_room',
                'room_name': room_name,
                'username': self.username
            }
            
            if not self.send_request(request):
                return False, "Failed to send request"
            
            response = self.receive_response()
            if response and response.get('status') == 'success':
                self.current_room_id = response.get('room_id')
                self.current_room_name = room_name
                self.room_joined.emit(self.current_room_id, room_name)
                self.room_updated.emit(self.current_room_id, room_name, 1)
                return True, response.get('message', 'Room created successfully')
            else:
                return False, response.get('message', 'Failed to create room') if response else 'No response from server'
                
        except Exception as e:
            self.log_message.emit(f"Create room error: {e}")
            return False, str(e)
    
    def join_room(self, room_id):
        """Join an existing room"""
        try:
            request = {
                'command': 'join_room',
                'room_id': room_id,
                'username': self.username
            }
            
            if not self.send_request(request):
                return False, "Failed to send request"
            
            response = self.receive_response()
            if response and response.get('status') == 'success':
                self.current_room_id = room_id
                self.current_room_name = response.get('room_name')
                self.room_joined.emit(room_id, self.current_room_name)
                self.list_rooms()  # Refresh room list to get updated member count
                return True, response.get('message', 'Joined room successfully')
            else:
                return False, response.get('message', 'Failed to join room') if response else 'No response from server'
                
        except Exception as e:
            self.log_message.emit(f"Join room error: {e}")
            return False, str(e)
    
    def leave_room(self):
        """Leave current room"""
        if not self.current_room_id:
            return True, "Not in any room"
        
        try:
            request = {
                'command': 'leave_room',
                'username': self.username
            }
            
            if not self.send_request(request):
                return False, "Failed to send request"
            
            response = self.receive_response()
            if response and response.get('status') == 'success':
                self.current_room_id = None
                self.current_room_name = None
                self.room_joined.emit("", "")
                self.list_rooms()  # Refresh room list
                return True, response.get('message', 'Left room successfully')
            else:
                return False, response.get('message', 'Failed to leave room') if response else 'No response from server'
                
        except Exception as e:
            self.log_message.emit(f"Leave room error: {e}")
            return False, str(e)
    
    def delete_room(self, room_id):
        """Delete a room (only by owner)"""
        try:
            request = {
                'command': 'delete_room',
                'room_id': room_id,
                'username': self.username
            }
            
            if not self.send_request(request):
                return False, "Failed to send request"
            
            response = self.receive_response()
            if response and response.get('status') == 'success':
                if self.current_room_id == room_id:
                    self.current_room_id = None
                    self.current_room_name = None
                    self.room_joined.emit("", "")
                self.list_rooms()  # Refresh room list
                return True, response.get('message', 'Room deleted successfully')
            else:
                return False, response.get('message', 'Failed to delete room') if response else 'No response from server'
                
        except Exception as e:
            self.log_message.emit(f"Delete room error: {e}")
            return False, str(e)
    
    def list_rooms(self):
        """List all available rooms"""
        try:
            request = {'command': 'list_rooms'}
            
            if not self.send_request(request):
                return
            
            response = self.receive_response()
            if response and response.get('status') == 'success':
                rooms = response.get('rooms', [])
                self.room_list_updated.emit(rooms)
                
                # Update room information if we're in a room
                if self.current_room_id:
                    for room in rooms:
                        if room.get('id') == self.current_room_id:
                            self.current_room_name = room.get('name')
                            self.room_updated.emit(
                                self.current_room_id,
                                room.get('name'),
                                room.get('member_count', 0)
                            )
                            break
            else:
                self.log_message.emit(f"List rooms failed: {response.get('message', 'No response') if response else 'No response from server'}")
                
        except Exception as e:
            self.log_message.emit(f"List rooms error: {e}")
    
    def upload_file(self, file_path, description=""):
        """Upload a file to the current room"""
        if not self.current_room_id:
            return False, "Must join a room before uploading files"
        
        try:
            file_size = os.path.getsize(file_path)
            filename = os.path.basename(file_path)
            
            if file_size > 500 * 1024 * 1024:
                return False, "File too large (max 500MB)"
            
            request = {
                'command': 'upload',
                'filename': filename,
                'file_size': file_size,
                'uploader': self.username,
                'description': description
            }
            
            if not self.send_request(request):
                return False, "Failed to send upload request"
            
            response = self.receive_response()
            if not response or response.get('status') != 'ready':
                return False, response.get('message', 'Server not ready for upload') if response else 'No response from server'
            
            self.upload_progress.emit(0)
            if not self.send_file_data(file_path):
                return False, "Failed to send file data"
            
            response = self.receive_response()
            if response and response.get('status') == 'success':
                self.upload_progress.emit(100)
                self.log_message.emit(f"File uploaded: {filename} (ID: {response.get('file_id')})")
                self.list_files()  # Refresh file list
                return True, "File uploaded successfully"
            else:
                return False, response.get('message', 'Upload failed') if response else 'No response from server'
                
        except Exception as e:
            self.log_message.emit(f"Upload error: {e}")
            return False, str(e)
    
    def download_file(self, file_id, output_path):
        """Download a file from the current room"""
        if not self.current_room_id:
            return False, "Must join a room before downloading files"
        
        try:
            request = {'command': 'download', 'file_id': file_id}
            
            if not self.send_request(request):
                return False, "Failed to send download request"
            
            response = self.receive_response()
            if not response or response.get('status') != 'success':
                return False, response.get('message', 'Download failed') if response else 'No response from server'
            
            filename = response.get('filename')
            file_size = response.get('file_size')
            output_file = os.path.join(output_path, filename)
            
            self.download_progress.emit(0)
            if self.receive_file_data(output_file, file_size):
                self.download_progress.emit(100)
                self.log_message.emit(f"File downloaded: {filename}")
                return True, f"File downloaded: {filename}"
            else:
                self.log_message.emit("Download failed: Incomplete file transfer")
                return False, "Incomplete file transfer"
                
        except Exception as e:
            self.log_message.emit(f"Download error: {e}")
            return False, str(e)
    
    def delete_file(self, file_id):
        """Delete a file from the current room"""
        if not self.current_room_id:
            return False, "Must join a room before deleting files"
        
        try:
            request = {'command': 'delete', 'file_id': file_id}
            
            if not self.send_request(request):
                return False, "Failed to send delete request"
            
            response = self.receive_response()
            if response and response.get('status') == 'success':
                self.list_files()  # Refresh file list
                return True, response.get('message', 'File deleted successfully')
            else:
                return False, response.get('message', 'Delete failed') if response else 'No response from server'
                
        except Exception as e:
            self.log_message.emit(f"Delete error: {e}")
            return False, str(e)
    
    def list_files(self):
        """List files in the current room"""
        if not self.current_room_id:
            self.file_list_updated.emit([])
            return
        
        try:
            request = {'command': 'list'}
            
            if not self.send_request(request):
                return
            
            response = self.receive_response()
            if response and response.get('status') == 'success':
                self.file_list_updated.emit(response.get('files', []))
            else:
                self.log_message.emit(f"List files failed: {response.get('message', 'No response') if response else 'No response from server'}")
                
        except Exception as e:
            self.log_message.emit(f"List files error: {e}")
    
    def attempt_reconnect(self):
        """Attempt to reconnect to server"""
        if not self.auto_reconnect or self.reconnect_attempts >= self.max_reconnect_attempts:
            return False
        
        self.reconnect_attempts += 1
        self.log_message.emit(f"Attempting to reconnect... ({self.reconnect_attempts}/{self.max_reconnect_attempts})")
        
        if self.connect_to_server():
            if self.current_room_id:
                self.join_room(self.current_room_id)
            return True
        
        return False
    
    def run(self):
        """Main client thread loop"""
        if not self.connect_to_server():
            return
        
        while self.running and self.connected:
            self.msleep(1000)

class ClientMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.client_thread = None
        self.current_room_info = {"id": None, "name": None}
        self.init_ui()
        self.apply_styles()
        
    def init_ui(self):
        """Initialize the user interface"""
        self.setWindowTitle("File Sharing Client")
        self.setGeometry(100, 100, 1200, 800)
        self.setMinimumSize(1000, 600)
        
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Disconnected")
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)
        
        connect_group = QGroupBox("🔗 Connection & User Settings")
        connect_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        connect_layout = QVBoxLayout(connect_group)
        
        conn_row = QHBoxLayout()
        conn_row.addWidget(QLabel("Host:"))
        self.host_input = QLineEdit("localhost")
        self.host_input.setMinimumWidth(120)
        conn_row.addWidget(self.host_input)
        
        conn_row.addWidget(QLabel("Port:"))
        self.port_input = QLineEdit("8888")
        self.port_input.setMaximumWidth(80)
        conn_row.addWidget(self.port_input)
        self.username_input = QLineEdit("Anonymous")
        conn_row.addWidget(QLabel("Username:"))
        self.username_input = QLineEdit(f"User_{str(uuid.uuid4())[:8]}")
        self.username_input.setMinimumWidth(120)
        conn_row.addWidget(self.username_input)
        
        conn_row.addStretch()
        connect_layout.addLayout(conn_row)
        
        conn_buttons = QHBoxLayout()
        self.connect_button = QPushButton("🔌 Connect")
        self.connect_button.clicked.connect(self.connect_to_server)
        self.connect_button.setMinimumHeight(35)
        conn_buttons.addWidget(self.connect_button)
        
        self.disconnect_button = QPushButton("❌ Disconnect")
        self.disconnect_button.clicked.connect(self.disconnect_from_server)
        self.disconnect_button.setEnabled(False)
        self.disconnect_button.setMinimumHeight(35)
        conn_buttons.addWidget(self.disconnect_button)
        
        conn_buttons.addStretch()
        connect_layout.addLayout(conn_buttons)
        
        layout.addWidget(connect_group)
        
        room_group = QGroupBox("🏠 Room Management")
        room_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        room_layout = QVBoxLayout(room_group)
        
        current_room_layout = QHBoxLayout()
        current_room_layout.addWidget(QLabel("Current Room:"))
        self.current_room_label = QLabel("None")
        self.current_room_label.setFont(QFont('Arial', 11, QFont.Bold))
        self.current_room_label.setStyleSheet("color: #e74c3c; padding: 5px; border: 1px solid #e74c3c; border-radius: 3px;")
        current_room_layout.addWidget(self.current_room_label)
        
        self.member_count_label = QLabel("Members: 0")
        self.member_count_label.setFont(QFont('Arial', 11))
        self.member_count_label.setStyleSheet("padding: 5px;")
        current_room_layout.addWidget(self.member_count_label)
        
        current_room_layout.addStretch()
        self.leave_room_button = QPushButton("🚪 Leave Room")
        self.leave_room_button.clicked.connect(self.leave_room)
        self.leave_room_button.setEnabled(False)
        self.leave_room_button.setMinimumHeight(30)
        current_room_layout.addWidget(self.leave_room_button)
        
        room_layout.addLayout(current_room_layout)
        
        room_actions = QHBoxLayout()
        self.create_room_button = QPushButton("➕ Create Room")
        self.create_room_button.clicked.connect(self.create_room)
        self.create_room_button.setEnabled(False)
        self.create_room_button.setMinimumHeight(35)
        room_actions.addWidget(self.create_room_button)
        
        self.join_room_button = QPushButton("🔗 Join Room")
        self.join_room_button.clicked.connect(self.show_room_list)
        self.join_room_button.setEnabled(False)
        self.join_room_button.setMinimumHeight(35)
        room_actions.addWidget(self.join_room_button)
        
        self.refresh_rooms_button = QPushButton("🔄 Refresh Rooms")
        self.refresh_rooms_button.clicked.connect(self.refresh_rooms)
        self.refresh_rooms_button.setEnabled(False)
        self.refresh_rooms_button.setMinimumHeight(35)
        room_actions.addWidget(self.refresh_rooms_button)
        
        room_actions.addStretch()
        room_layout.addLayout(room_actions)
        
        layout.addWidget(room_group)
        
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #bdc3c7;
                border-radius: 5px;
            }
            QTabBar::tab {
                background: #ecf0f1;
                border: 1px solid #bdc3c7;
                padding: 8px 16px;
                margin-right: 2px;
                border-top-left-radius: 5px;
                border-top-right-radius: 5px;
            }
            QTabBar::tab:selected {
                background: #3498db;
                color: white;
            }
            QTabBar::tab:hover {
                background: #5dade2;
                color: white;
            }
        """)
        
        files_tab = QWidget()
        files_layout = QVBoxLayout(files_tab)
        
        file_ops_group = QGroupBox("📁 File Operations")
        file_ops_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        file_ops_layout = QHBoxLayout(file_ops_group)
        
        self.upload_button = QPushButton("⬆️ Upload File")
        self.upload_button.clicked.connect(self.upload_file)
        self.upload_button.setEnabled(False)
        self.upload_button.setMinimumHeight(35)
        file_ops_layout.addWidget(self.upload_button)
        
        self.download_button = QPushButton("⬇️ Download Selected")
        self.download_button.clicked.connect(self.download_file)
        self.download_button.setEnabled(False)
        self.download_button.setMinimumHeight(35)
        file_ops_layout.addWidget(self.download_button)
        
        self.delete_file_button = QPushButton("🗑️ Delete Selected")
        self.delete_file_button.clicked.connect(self.delete_file)
        self.delete_file_button.setEnabled(False)
        self.delete_file_button.setMinimumHeight(35)
        file_ops_layout.addWidget(self.delete_file_button)
        
        self.refresh_files_button = QPushButton("🔄 Refresh Files")
        self.refresh_files_button.clicked.connect(self.refresh_files)
        self.refresh_files_button.setEnabled(False)
        self.refresh_files_button.setMinimumHeight(35)
        file_ops_layout.addWidget(self.refresh_files_button)
        
        file_ops_layout.addStretch()
        files_layout.addWidget(file_ops_group)
        
        progress_group = QGroupBox("📊 Transfer Progress")
        progress_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        progress_layout = QVBoxLayout(progress_group)
        
        upload_progress_layout = QHBoxLayout()
        upload_progress_layout.addWidget(QLabel("Upload:"))
        self.upload_progress = QProgressBar()
        self.upload_progress.setVisible(False)
        self.upload_progress.setStyleSheet("""
            QProgressBar {
                border: 1px solid #bdc3c7;
                border-radius: 5px;
                text-align: center;
                height: 20px;
            }
            QProgressBar::chunk {
                background-color: #27ae60;
                border-radius: 5px;
            }
        """)
        upload_progress_layout.addWidget(self.upload_progress)
        progress_layout.addLayout(upload_progress_layout)
        
        download_progress_layout = QHBoxLayout()
        download_progress_layout.addWidget(QLabel("Download:"))
        self.download_progress = QProgressBar()
        self.download_progress.setVisible(False)
        self.download_progress.setStyleSheet("""
            QProgressBar {
                border: 1px solid #bdc3c7;
                border-radius: 5px;
                text-align: center;
                height: 20px;
            }
            QProgressBar::chunk {
                background-color: #3498db;
                border-radius: 5px;
            }
        """)
        download_progress_layout.addWidget(self.download_progress)
        progress_layout.addLayout(download_progress_layout)
        
        files_layout.addWidget(progress_group)
        
        files_list_group = QGroupBox("📋 Files in Current Room")
        files_list_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        files_list_layout = QVBoxLayout(files_list_group)
        
        self.files_table = QTableWidget()
        self.files_table.setColumnCount(6)
        self.files_table.setHorizontalHeaderLabels(["ID", "Name", "Size", "Type", "Uploader", "Date"])
        header = self.files_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.files_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.files_table.setAlternatingRowColors(True)
        self.files_table.setStyleSheet("""
            QTableWidget {
                gridline-color: #bdc3c7;
                background-color: #ffffff;
                alternate-background-color: #f8f9fa;
            }
            QTableWidget::item:selected {
                background-color: #3498db;
                color: white;
            }
        """)
        files_list_layout.addWidget(self.files_table)
        
        files_layout.addWidget(files_list_group)
        self.tab_widget.addTab(files_tab, "📁 Files")
        
        rooms_tab = QWidget()
        rooms_layout = QVBoxLayout(rooms_tab)
        
        rooms_list_group = QGroupBox("🏠 Available Rooms")
        rooms_list_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        rooms_list_layout = QVBoxLayout(rooms_list_group)
        
        self.rooms_table = QTableWidget()
        self.rooms_table.setColumnCount(5)
        self.rooms_table.setHorizontalHeaderLabels(["ID", "Name", "Owner", "Members", "Created"])
        rooms_header = self.rooms_table.horizontalHeader()
        rooms_header.setSectionResizeMode(QHeaderView.Stretch)
        rooms_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        rooms_header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        rooms_header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.rooms_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.rooms_table.setAlternatingRowColors(True)
        self.rooms_table.setStyleSheet("""
            QTableWidget {
                gridline-color: #bdc3c7;
                background-color: #ffffff;
                alternate-background-color: #f8f9fa;
            }
            QTableWidget::item:selected {
                background-color: #3498db;
                color: white;
            }
        """)
        self.rooms_table.doubleClicked.connect(self.join_selected_room)
        rooms_list_layout.addWidget(self.rooms_table)
        
        room_table_actions = QHBoxLayout()
        join_selected_button = QPushButton("🔗 Join Selected Room")
        join_selected_button.clicked.connect(self.join_selected_room)
        join_selected_button.setMinimumHeight(35)
        room_table_actions.addWidget(join_selected_button)
        
        self.delete_room_button = QPushButton("🗑️ Delete Selected Room")
        self.delete_room_button.clicked.connect(self.delete_selected_room)
        self.delete_room_button.setEnabled(False)
        self.delete_room_button.setMinimumHeight(35)
        room_table_actions.addWidget(self.delete_room_button)
        
        room_table_actions.addStretch()
        rooms_list_layout.addLayout(room_table_actions)
        
        rooms_layout.addWidget(rooms_list_group)
        self.tab_widget.addTab(rooms_tab, "🏠 Rooms")
        
        log_tab = QWidget()
        log_layout = QVBoxLayout(log_tab)
        
        log_group = QGroupBox("📝 Activity Log")
        log_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        log_group_layout = QVBoxLayout(log_group)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont('Consolas', 9))
        self.log_text.setStyleSheet("""
            QTextEdit {
                background-color: #2c3e50;
                color: #ecf0f1;
                border: 1px solid #34495e;
                border-radius: 5px;
                padding: 5px;
            }
        """)
        log_group_layout.addWidget(self.log_text)
        
        log_controls = QHBoxLayout()
        clear_log_button = QPushButton("🧹 Clear Log")
        clear_log_button.clicked.connect(self.clear_log)
        clear_log_button.setMinimumHeight(35)
        log_controls.addWidget(clear_log_button)
        log_controls.addStretch()
        log_group_layout.addLayout(log_controls)
        
        log_layout.addWidget(log_group)
        self.tab_widget.addTab(log_tab, "📝 Log")
        
        layout.addWidget(self.tab_widget)
        
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.auto_refresh)
        
        self.log("File Sharing Client GUI initialized")
    
    def apply_styles(self):
        """Apply modern styling to the application"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f8f9fa;
            }
            QWidget {
                background-color: #ffffff;
            }
            QGroupBox {
                font-size: 12px;
                font-weight: bold;
                border: 2px solid #bdc3c7;
                border-radius: 8px;
                margin-top: 1ex;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: #2c3e50;
            }
            QPushButton {
                background-color: #3498db;
                border: none;
                color: white;
                padding: 8px 16px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
            QPushButton:pressed {
                background-color: #21618c;
            }
            QPushButton:disabled {
                background-color: #bdc3c7;
                color: #7f8c8d;
            }
            QLineEdit {
                border: 2px solid #bdc3c7;
                border-radius: 5px;
                padding: 5px;
                font-size: 11px;
                background-color: white;
            }
            QLineEdit:focus {
                border-color: #3498db;
            }
            QLabel {
                color: #2c3e50;
                font-size: 11px;
            }
            QStatusBar {
                background-color: #ecf0f1;
                border-top: 1px solid #bdc3c7;
                color: #2c3e50;
                font-weight: bold;
            }
        """)
    
    def connect_to_server(self):
        """Connect to the server"""
        host = self.host_input.text().strip()
        username = self.username_input.text().strip()
        
        if not host or not username:
            QMessageBox.warning(self, "Warning", "Please enter both host and username")
            return
        
        try:
            port = int(self.port_input.text())
        except ValueError:
            QMessageBox.critical(self, "Error", "Invalid port number")
            return
        
        self.client_thread = ClientThread(host, port)
        self.client_thread.set_username(username)
        
        self.client_thread.log_message.connect(self.log)
        self.client_thread.connection_status_changed.connect(self.on_connection_status_changed)
        self.client_thread.room_list_updated.connect(self.update_room_list)
        self.client_thread.file_list_updated.connect(self.update_file_list)
        self.client_thread.room_joined.connect(self.on_room_joined)
        self.client_thread.upload_progress.connect(self.on_upload_progress)
        self.client_thread.download_progress.connect(self.on_download_progress)
        self.client_thread.room_updated.connect(self.on_room_updated)
        
        self.client_thread.start()
        
        self.refresh_timer.start(5000)  # Refresh every 5 seconds
    
    def disconnect_from_server(self):
        """Disconnect from the server"""
        if self.client_thread:
            self.client_thread.disconnect_from_server()
            self.client_thread.wait(3000)
            self.client_thread = None
        
        self.refresh_timer.stop()
        self.reset_ui_state()
        self.log("Disconnected from server")
    
    def reset_ui_state(self):
        """Reset UI to disconnected state"""
        self.connect_button.setEnabled(True)
        self.disconnect_button.setEnabled(False)
        self.create_room_button.setEnabled(False)
        self.join_room_button.setEnabled(False)
        self.refresh_rooms_button.setEnabled(False)
        self.upload_button.setEnabled(False)
        self.download_button.setEnabled(False)
        self.delete_file_button.setEnabled(False)
        self.refresh_files_button.setEnabled(False)
        self.leave_room_button.setEnabled(False)
        self.delete_room_button.setEnabled(False)
        
        self.host_input.setEnabled(True)
        self.port_input.setEnabled(True)
        self.username_input.setEnabled(True)
        
        self.current_room_label.setText("None")
        self.current_room_label.setStyleSheet("color: #e74c3c; padding: 5px; border: 1px solid #e74c3c; border-radius: 3px;")
        self.member_count_label.setText("Members: 0")
        self.status_bar.showMessage("Disconnected")
        self.status_bar.setStyleSheet("color: #e74c3c;")
        
        self.files_table.setRowCount(0)
        self.rooms_table.setRowCount(0)
        
        self.upload_progress.setVisible(False)
        self.download_progress.setVisible(False)
    
    def on_connection_status_changed(self, connected, message):
        """Handle connection status change"""
        if connected:
            self.connect_button.setEnabled(False)
            self.disconnect_button.setEnabled(True)
            self.create_room_button.setEnabled(True)
            self.join_room_button.setEnabled(True)
            self.refresh_rooms_button.setEnabled(True)
            
            self.host_input.setEnabled(False)
            self.port_input.setEnabled(False)
            self.username_input.setEnabled(False)
            
            self.status_bar.showMessage(message)
            self.status_bar.setStyleSheet("color: #27ae60;")
            
            if self.client_thread:
                self.client_thread.list_rooms()
        else:
            self.reset_ui_state()
            self.status_bar.showMessage(message)
            self.status_bar.setStyleSheet("color: #e74c3c;")
    
    def on_room_joined(self, room_id, room_name):
        """Handle room joined event"""
        if room_id and room_name:
            self.current_room_info = {"id": room_id, "name": room_name}
            self.current_room_label.setText(f"{room_name} ({room_id})")
            self.current_room_label.setStyleSheet("color: #27ae60; padding: 5px; border: 1px solid #27ae60; border-radius: 3px; background-color: #d5f4e6;")
            self.leave_room_button.setEnabled(True)
            
            self.upload_button.setEnabled(True)
            self.download_button.setEnabled(True)
            self.delete_file_button.setEnabled(True)
            self.refresh_files_button.setEnabled(True)
            
            if self.client_thread:
                self.client_thread.list_files()
            
            self.log(f"Joined room: {room_name}")
        else:
            self.current_room_info = {"id": None, "name": None}
            self.current_room_label.setText("None")
            self.current_room_label.setStyleSheet("color: #e74c3c; padding: 5px; border: 1px solid #e74c3c; border-radius: 3px;")
            self.member_count_label.setText("Members: 0")
            self.leave_room_button.setEnabled(False)
            
            self.upload_button.setEnabled(False)
            self.download_button.setEnabled(False)
            self.delete_file_button.setEnabled(False)
            self.refresh_files_button.setEnabled(False)
            
            self.files_table.setRowCount(0)
    
    def on_room_updated(self, room_id, room_name, member_count):
        """Handle room update event"""
        if room_id == self.current_room_info["id"]:
            self.current_room_info["name"] = room_name
            self.current_room_label.setText(f"{room_name} ({room_id})")
            self.member_count_label.setText(f"Members: {member_count}")
            self.log(f"Room updated: {room_name} ({member_count} member(s))")
    
    def on_upload_progress(self, progress):
        """Handle upload progress"""
        self.upload_progress.setValue(progress)
        if progress == 0:
            self.upload_progress.setVisible(True)
        elif progress == 100:
            self.upload_progress.setVisible(False)
            if self.client_thread:
                self.client_thread.list_files()
    
    def on_download_progress(self, progress):
        """Handle download progress"""
        self.download_progress.setValue(progress)
        if progress == 0:
            self.download_progress.setVisible(True)
        elif progress == 100:
            self.download_progress.setVisible(False)
    
    def create_room(self):
        """Create a new room"""
        if not self.client_thread or not self.client_thread.running:
            QMessageBox.warning(self, "Warning", "Not connected to server")
            return
        
        room_name, ok = QInputDialog.getText(
            self, 'Create Room', 'Enter room name (1-50 characters):')
        
        if ok and room_name.strip():
            room_name = room_name.strip()
            if len(room_name) > 50:
                QMessageBox.warning(self, "Warning", "Room name too long (max 50 characters)")
                return
            
            success, message = self.client_thread.create_room(room_name)
            if success:
                QMessageBox.information(self, "Success", message)
                if self.client_thread:
                    self.client_thread.list_rooms()
            else:
                QMessageBox.critical(self, "Error", message)
    
    def show_room_list(self):
        """Show room list for joining"""
        self.tab_widget.setCurrentIndex(1)
        if self.client_thread:
            self.client_thread.list_rooms()
    
    def join_selected_room(self):
        """Join the selected room from the table"""
        if not self.client_thread or not self.client_thread.running:
            QMessageBox.warning(self, "Warning", "Not connected to server")
            return
        
        selected = self.rooms_table.selectedItems()
        if not selected:
            QMessageBox.warning(self, "Warning", "Please select a room to join")
            return
        
        room_id = self.rooms_table.item(selected[0].row(), 0).text()
        room_name = self.rooms_table.item(selected[0].row(), 1).text()
        
        reply = QMessageBox.question(
            self, 'Join Room', 
            f'Join room "{room_name}"?',
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            success, message = self.client_thread.join_room(room_id)
            if success:
                QMessageBox.information(self, "Success", message)
                self.tab_widget.setCurrentIndex(0)
            else:
                QMessageBox.critical(self, "Error", message)
    
    def leave_room(self):
        """Leave the current room"""
        if not self.current_room_info["id"]:
            return
        
        reply = QMessageBox.question(
            self, 'Leave Room', 
            f'Leave room "{self.current_room_info["name"]}"?',
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            if self.client_thread:
                success, message = self.client_thread.leave_room()
                if success:
                    QMessageBox.information(self, "Success", message)
                    self.on_room_joined("", "")
    
    def delete_selected_room(self):
        """Delete the selected room (only if owner)"""
        if not self.client_thread or not self.client_thread.running:
            QMessageBox.warning(self, "Warning", "Not connected to server")
            return
        
        selected = self.rooms_table.selectedItems()
        if not selected:
            QMessageBox.warning(self, "Warning", "Please select a room to delete")
            return
        
        room_id = self.rooms_table.item(selected[0].row(), 0).text()
        room_name = self.rooms_table.item(selected[0].row(), 1).text()
        room_owner = self.rooms_table.item(selected[0].row(), 2).text()
        
        if room_owner != self.username_input.text():
            QMessageBox.warning(self, "Warning", "Only the room owner can delete the room")
            return
        
        reply = QMessageBox.question(
            self, 'Delete Room', 
            f'Are you sure you want to delete room "{room_name}"?\nThis will delete all files in the room!',
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            success, message = self.client_thread.delete_room(room_id)
            if success:
                QMessageBox.information(self, "Success", message)
                if self.client_thread:
                    self.client_thread.list_rooms()
            else:
                QMessageBox.critical(self, "Error", message)
    
    def refresh_rooms(self):
        """Refresh the rooms list"""
        if self.client_thread and self.client_thread.running:
            self.client_thread.list_rooms()
    
    def refresh_files(self):
        """Refresh the files list"""
        if self.client_thread and self.client_thread.running:
            self.client_thread.list_files()
    
    def auto_refresh(self):
        """Auto-refresh data periodically"""
        if self.client_thread and self.client_thread.running and self.client_thread.connected:
            if self.tab_widget.currentIndex() == 1:
                self.client_thread.list_rooms()
            elif self.current_room_info["id"]:
                self.client_thread.list_files()
    
    def upload_file(self):
        """Upload a file"""
        if not self.client_thread or not self.client_thread.running:
            QMessageBox.warning(self, "Warning", "Not connected to server")
            return
        
        if not self.current_room_info["id"]:
            QMessageBox.warning(self, "Warning", "Must join a room before uploading files")
            return
        
        file_path, _ = QFileDialog.getOpenFileName(self, "Select File to Upload")
        if not file_path:
            return
        
        description, ok = QInputDialog.getText(
            self, 'File Description', 'Enter file description (optional):')
        
        if not ok:
            description = ""
        
        success, message = self.client_thread.upload_file(file_path, description)
        if not success:
            QMessageBox.critical(self, "Upload Error", message)
    
    def download_file(self):
        """Download selected file"""
        if not self.client_thread or not self.client_thread.running:
            QMessageBox.warning(self, "Warning", "Not connected to server")
            return
        
        selected = self.files_table.selectedItems()
        if not selected:
            QMessageBox.warning(self, "Warning", "Please select a file to download")
            return
        
        file_id = self.files_table.item(selected[0].row(), 0).text()
        filename = self.files_table.item(selected[0].row(), 1).text()
        
        output_dir = QFileDialog.getExistingDirectory(self, "Select Download Directory")
        if not output_dir:
            return
        
        success, message = self.client_thread.download_file(file_id, output_dir)
        if success:
            QMessageBox.information(self, "Success", message)
        else:
            QMessageBox.critical(self, "Download Error", message)
    
    def delete_file(self):
        """Delete selected file"""
        if not self.client_thread or not self.client_thread.running:
            QMessageBox.warning(self, "Warning", "Not connected to server")
            return
        
        selected = self.files_table.selectedItems()
        if not selected:
            QMessageBox.warning(self, "Warning", "Please select a file to delete")
            return
        
        file_id = self.files_table.item(selected[0].row(), 0).text()
        filename = self.files_table.item(selected[0].row(), 1).text()
        
        reply = QMessageBox.question(
            self, 'Delete File', 
            f'Are you sure you want to delete "{filename}"?',
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            success, message = self.client_thread.delete_file(file_id)
            if success:
                QMessageBox.information(self, "Success", message)
                if self.client_thread:
                    self.client_thread.list_files()
            else:
                QMessageBox.critical(self, "Delete Error", message)
    
    def update_room_list(self, rooms):
        """Update the rooms table"""
        self.rooms_table.setRowCount(len(rooms))
        
        current_username = self.username_input.text()
        
        for row, room in enumerate(rooms):
            self.rooms_table.setItem(row, 0, QTableWidgetItem(room.get('id', '')))
            self.rooms_table.setItem(row, 1, QTableWidgetItem(room['name']))
            self.rooms_table.setItem(row, 2, QTableWidgetItem(room['owner']))
            self.rooms_table.setItem(row, 3, QTableWidgetItem(str(room['member_count'])))
            self.rooms_table.setItem(row, 4, QTableWidgetItem(room['created_at']))
            
            if room['owner'] == current_username:
                self.delete_room_button.setEnabled(True)
    
    def update_file_list(self, files):
        """Update the files table"""
        self.files_table.setRowCount(len(files))
        
        for row, file in enumerate(files):
            self.files_table.setItem(row, 0, QTableWidgetItem(file['id']))
            self.files_table.setItem(row, 1, QTableWidgetItem(file['name']))
            self.files_table.setItem(row, 2, QTableWidgetItem(self.format_size(file['size'])))
            self.files_table.setItem(row, 3, QTableWidgetItem(file['type']))
            self.files_table.setItem(row, 4, QTableWidgetItem(file['uploader']))
            self.files_table.setItem(row, 5, QTableWidgetItem(file['date']))
    
    def format_size(self, size_bytes):
        """Format file size in human readable format"""
        if size_bytes == 0:
            return "0B"
        
        size_units = ['B', 'KB', 'MB', 'GB']
        i = 0
        while size_bytes >= 1024 and i < len(size_units) - 1:
            size_bytes /= 1024.0
            i += 1
        
        return f"{size_bytes:.1f}{size_units[i]}"
    
    def log(self, message):
        """Add message to log"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"<span style='color: #3498db;'>[{timestamp}]</span> <span style='color: #ecf0f1;'>{message}</span>")
        
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def clear_log(self):
        """Clear the log"""
        self.log_text.clear()
        self.log("Log cleared")
    
    def closeEvent(self, event):
        """Handle window close event"""
        if self.client_thread:
            self.disconnect_from_server()
        event.accept()

def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    app.setApplicationName("File Sharing Client")
    app.setApplicationVersion("2.0")
    
    window = ClientMainWindow()
    window.show()
    
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()