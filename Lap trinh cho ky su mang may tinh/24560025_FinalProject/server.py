#!/usr/bin/env python3
# server.py - Enhanced File Sharing Server with Room Management
import socket
import threading
import json
import os
import struct
import uuid
import logging
from datetime import datetime
import mimetypes
import hashlib

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class Room:
    def __init__(self, room_id, name, owner):
        self.id = room_id
        self.name = name
        self.owner = owner
        self.members = set()
        self.files = {}  # file_id -> file_info
        self.created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Create room directory
        self.room_dir = os.path.join("rooms", room_id)
        os.makedirs(self.room_dir, exist_ok=True)
    
    def add_member(self, username):
        self.members.add(username)
        logger.info(f"User {username} joined room {self.name} ({self.id})")
    
    def remove_member(self, username):
        self.members.discard(username)
        logger.info(f"User {username} left room {self.name} ({self.id})")
    
    def add_file(self, file_info):
        self.files[file_info['id']] = file_info
        logger.info(f"File {file_info['name']} added to room {self.name}")
    
    def remove_file(self, file_id):
        if file_id in self.files:
            file_info = self.files[file_id]
            file_path = os.path.join(self.room_dir, file_info['filename'])
            
            # Delete physical file
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                del self.files[file_id]
                logger.info(f"File {file_info['name']} removed from room {self.name}")
                return True
            except Exception as e:
                logger.error(f"Error deleting file: {e}")
                return False
        return False
    
    def get_file_list(self):
        file_list = []
        for file_id, file_info in self.files.items():
            file_list.append({
                'id': file_id,
                'name': file_info['name'],
                'size': file_info['size'],
                'type': file_info['type'],
                'uploader': file_info['uploader'],
                'date': file_info['date']
            })
        return file_list
    
    def cleanup(self):
        """Clean up room directory and files"""
        try:
            import shutil
            if os.path.exists(self.room_dir):
                shutil.rmtree(self.room_dir)
            logger.info(f"Room {self.name} directory cleaned up")
        except Exception as e:
            logger.error(f"Error cleaning up room directory: {e}")

class FileServer:
    def __init__(self, host='0.0.0.0', port=8888):
        self.host = host
        self.port = port
        self.socket = None
        self.running = False
        self.clients = {}  # socket -> client_info
        self.rooms = {}    # room_id -> Room object
        self.client_rooms = {}  # socket -> room_id
        
        # Create base directories
        os.makedirs("rooms", exist_ok=True)
        
    def start_server(self):
        """Start the file server"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.bind(('0.0.0.0', self.port))
            self.socket.listen(10)
            self.running = True
            
            logger.info(f"Server started on {self.host}:{self.port}")
            print(f"File sharing server started on {self.host}:{self.port}")
            
            while self.running:
                try:
                    client_socket, client_address = self.socket.accept()
                    logger.info(f"New client connected: {client_address}")
                    
                    # Initialize client info
                    self.clients[client_socket] = {
                        'address': client_address,
                        'username': 'Anonymous',
                        'connected_at': datetime.now()
                    }
                    
                    # Start client handler thread
                    client_thread = threading.Thread(
                        target=self.handle_client,
                        args=(client_socket,),
                        daemon=True
                    )
                    client_thread.start()
                    
                except Exception as e:
                    if self.running:
                        logger.error(f"Error accepting client: {e}")
                        
        except Exception as e:
            logger.error(f"Server error: {e}")
        finally:
            self.cleanup()
    
    def stop_server(self):
        """Stop the server"""
        self.running = False
        if self.socket:
            self.socket.close()
        logger.info("Server stopped")
    
    def cleanup(self):
        """Clean up server resources"""
        for client_socket in list(self.clients.keys()):
            try:
                client_socket.close()
            except:
                pass
        self.clients.clear()
        self.client_rooms.clear()
    
    def send_response(self, client_socket, response):
        """Send JSON response to client"""
        try:
            response_data = json.dumps(response).encode('utf-8')
            length_data = struct.pack('!I', len(response_data))
            client_socket.send(length_data + response_data)
            return True
        except Exception as e:
            logger.error(f"Error sending response: {e}")
            return False
    
    def receive_request(self, client_socket, timeout=30):
        """Receive JSON request from client"""
        try:
            client_socket.settimeout(timeout)
            
            # Receive length
            length_data = client_socket.recv(4)
            if not length_data:
                return None
            
            length = struct.unpack('!I', length_data)[0]
            
            # Prevent memory attacks
            if length > 10 * 1024 * 1024:  # 10MB limit
                return None
            
            # Receive data
            data = b''
            while len(data) < length:
                chunk = client_socket.recv(min(8192, length - len(data)))
                if not chunk:
                    return None
                data += chunk
            
            return json.loads(data.decode('utf-8'))
            
        except socket.timeout:
            return None
        except Exception as e:
            logger.error(f"Error receiving request: {e}")
            return None
    
    def handle_client(self, client_socket):
        """Handle individual client connection"""
        try:
            while self.running:
                request = self.receive_request(client_socket)
                if not request:
                    break
                
                command = request.get('command')
                logger.info(f"Received command: {command} from {self.clients[client_socket]['address']}")
                
                # Update username if provided
                if 'username' in request:
                    self.clients[client_socket]['username'] = request['username']
                
                # Handle commands
                if command == 'create_room':
                    self.handle_create_room(client_socket, request)
                elif command == 'join_room':
                    self.handle_join_room(client_socket, request)
                elif command == 'leave_room':
                    self.handle_leave_room(client_socket, request)
                elif command == 'delete_room':
                    self.handle_delete_room(client_socket, request)
                elif command == 'list_rooms':
                    self.handle_list_rooms(client_socket, request)
                elif command == 'upload':
                    self.handle_upload(client_socket, request)
                elif command == 'download':
                    self.handle_download(client_socket, request)
                elif command == 'delete':
                    self.handle_delete_file(client_socket, request)
                elif command == 'list':
                    self.handle_list_files(client_socket, request)
                else:
                    self.send_response(client_socket, {
                        'status': 'error',
                        'message': f'Unknown command: {command}'
                    })
                    
        except Exception as e:
            logger.error(f"Client handler error: {e}")
        finally:
            self.disconnect_client(client_socket)
    
    def disconnect_client(self, client_socket):
        """Clean up client connection"""
        try:
            # Remove from room if in one
            if client_socket in self.client_rooms:
                room_id = self.client_rooms[client_socket]
                if room_id in self.rooms:
                    username = self.clients[client_socket]['username']
                    self.rooms[room_id].remove_member(username)
                del self.client_rooms[client_socket]
            
            # Remove client info
            if client_socket in self.clients:
                logger.info(f"Client disconnected: {self.clients[client_socket]['address']}")
                del self.clients[client_socket]
            
            client_socket.close()
            
        except Exception as e:
            logger.error(f"Error disconnecting client: {e}")
    
    def handle_create_room(self, client_socket, request):
        """Handle room creation"""
        try:
            room_name = request.get('room_name', '').strip()
            username = request.get('username', 'Anonymous')
            
            if not room_name:
                self.send_response(client_socket, {
                    'status': 'error',
                    'message': 'Room name is required'
                })
                return
            
            if len(room_name) > 50:
                self.send_response(client_socket, {
                    'status': 'error',
                    'message': 'Room name too long (max 50 characters)'
                })
                return
            
            # Generate unique room ID
            room_id = str(uuid.uuid4())[:8]
            
            # Create room
            room = Room(room_id, room_name, username)
            room.add_member(username)
            self.rooms[room_id] = room
            self.client_rooms[client_socket] = room_id
            
            self.send_response(client_socket, {
                'status': 'success',
                'message': f'Room "{room_name}" created successfully',
                'room_id': room_id,
                'room_name': room_name
            })
            
            logger.info(f"Room created: {room_name} ({room_id}) by {username}")
            
        except Exception as e:
            logger.error(f"Create room error: {e}")
            self.send_response(client_socket, {
                'status': 'error',
                'message': 'Failed to create room'
            })
    
    def handle_join_room(self, client_socket, request):
        """Handle room joining"""
        try:
            room_id = request.get('room_id', '').strip()
            username = request.get('username', 'Anonymous')
            
            if not room_id:
                self.send_response(client_socket, {
                    'status': 'error',
                    'message': 'Room ID is required'
                })
                return
            
            if room_id not in self.rooms:
                self.send_response(client_socket, {
                    'status': 'error',
                    'message': 'Room not found'
                })
                return
            
            # Leave current room if in one
            if client_socket in self.client_rooms:
                old_room_id = self.client_rooms[client_socket]
                if old_room_id in self.rooms:
                    self.rooms[old_room_id].remove_member(username)
            
            # Join new room
            room = self.rooms[room_id]
            room.add_member(username)
            self.client_rooms[client_socket] = room_id
            
            self.send_response(client_socket, {
                'status': 'success',
                'message': f'Joined room "{room.name}" successfully',
                'room_id': room_id,
                'room_name': room.name
            })
            
            logger.info(f"User {username} joined room {room.name} ({room_id})")
            
        except Exception as e:
            logger.error(f"Join room error: {e}")
            self.send_response(client_socket, {
                'status': 'error',
                'message': 'Failed to join room'
            })
    
    def handle_leave_room(self, client_socket, request):
        """Handle leaving room"""
        try:
            username = self.clients[client_socket]['username']
            
            if client_socket not in self.client_rooms:
                self.send_response(client_socket, {
                    'status': 'success',
                    'message': 'Not in any room'
                })
                return
            
            room_id = self.client_rooms[client_socket]
            if room_id in self.rooms:
                self.rooms[room_id].remove_member(username)
            
            del self.client_rooms[client_socket]
            
            self.send_response(client_socket, {
                'status': 'success',
                'message': 'Left room successfully'
            })
            
        except Exception as e:
            logger.error(f"Leave room error: {e}")
            self.send_response(client_socket, {
                'status': 'error',
                'message': 'Failed to leave room'
            })
    
    def handle_delete_room(self, client_socket, request):
        """Handle room deletion"""
        try:
            room_id = request.get('room_id', '').strip()
            username = self.clients[client_socket]['username']
            
            if not room_id or room_id not in self.rooms:
                self.send_response(client_socket, {
                    'status': 'error',
                    'message': 'Room not found'
                })
                return
            
            room = self.rooms[room_id]
            
            # Check if user is the owner
            if room.owner != username:
                self.send_response(client_socket, {
                    'status': 'error',
                    'message': 'Only the room owner can delete the room'
                })
                return
            
            # Remove all clients from the room
            clients_to_remove = []
            for client_sock, client_room_id in self.client_rooms.items():
                if client_room_id == room_id:
                    clients_to_remove.append(client_sock)
            
            for client_sock in clients_to_remove:
                del self.client_rooms[client_sock]
            
            # Clean up room
            room.cleanup()
            del self.rooms[room_id]
            
            self.send_response(client_socket, {
                'status': 'success',
                'message': f'Room "{room.name}" deleted successfully'
            })
            
            logger.info(f"Room {room.name} ({room_id}) deleted by {username}")
            
        except Exception as e:
            logger.error(f"Delete room error: {e}")
            self.send_response(client_socket, {
                'status': 'error',
                'message': 'Failed to delete room'
            })
    
    def handle_list_rooms(self, client_socket, request):
        """Handle listing rooms"""
        try:
            rooms_list = []
            for room_id, room in self.rooms.items():
                rooms_list.append({
                    'id': room_id,
                    'name': room.name,
                    'owner': room.owner,
                    'member_count': len(room.members),
                    'created_at': room.created_at
                })
            
            self.send_response(client_socket, {
                'status': 'success',
                'rooms': rooms_list
            })
            
        except Exception as e:
            logger.error(f"List rooms error: {e}")
            self.send_response(client_socket, {
                'status': 'error',
                'message': 'Failed to list rooms'
            })
    
    def handle_upload(self, client_socket, request):
        """Handle file upload"""
        try:
            # Check if client is in a room
            if client_socket not in self.client_rooms:
                self.send_response(client_socket, {
                    'status': 'error',
                    'message': 'Must join a room before uploading files'
                })
                return
            
            room_id = self.client_rooms[client_socket]
            if room_id not in self.rooms:
                self.send_response(client_socket, {
                    'status': 'error',
                    'message': 'Room not found'
                })
                return
            
            room = self.rooms[room_id]
            
            filename = request.get('filename', '')
            file_size = request.get('file_size', 0)
            uploader = request.get('uploader', 'Anonymous')
            description = request.get('description', '')
            
            if not filename:
                self.send_response(client_socket, {
                    'status': 'error',
                    'message': 'Filename is required'
                })
                return
            
            # Check file size limit (100MB)
            if file_size > 500 * 1024 * 1024:
                self.send_response(client_socket, {
                    'status': 'error',
                    'message': 'File too large (max 500MB)'
                })
                return
            
            # Generate file ID and path
            file_id = str(uuid.uuid4())[:12]
            file_extension = os.path.splitext(filename)[1]
            stored_filename = f"{file_id}{file_extension}"
            file_path = os.path.join(room.room_dir, stored_filename)
            
            # Send ready response
            self.send_response(client_socket, {
                'status': 'ready',
                'message': 'Ready to receive file'
            })
            
            # Receive file data
            received = 0
            with open(file_path, 'wb') as f:
                while received < file_size:
                    chunk_size = min(8192, file_size - received)
                    chunk = client_socket.recv(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    received += len(chunk)
            
            if received != file_size:
                # Clean up incomplete file
                try:
                    os.remove(file_path)
                except:
                    pass
                self.send_response(client_socket, {
                    'status': 'error',
                    'message': 'Incomplete file transfer'
                })
                return
            
            # Get file type
            file_type, _ = mimetypes.guess_type(filename)
            if not file_type:
                file_type = 'application/octet-stream'
            
            # Create file info
            file_info = {
                'id': file_id,
                'name': filename,
                'filename': stored_filename,
                'size': file_size,
                'type': file_type,
                'uploader': uploader,
                'description': description,
                'date': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
            # Add to room
            room.add_file(file_info)
            
            self.send_response(client_socket, {
                'status': 'success',
                'message': 'File uploaded successfully',
                'file_id': file_id
            })
            
            logger.info(f"File uploaded: {filename} ({file_id}) to room {room.name}")
            
        except Exception as e:
            logger.error(f"Upload error: {e}")
            self.send_response(client_socket, {
                'status': 'error',
                'message': 'Upload failed'
            })
    
    def handle_download(self, client_socket, request):
        """Handle file download"""
        try:
            # Check if client is in a room
            if client_socket not in self.client_rooms:
                self.send_response(client_socket, {
                    'status': 'error',
                    'message': 'Must join a room before downloading files'
                })
                return
            
            room_id = self.client_rooms[client_socket]
            if room_id not in self.rooms:
                self.send_response(client_socket, {
                    'status': 'error',
                    'message': 'Room not found'
                })
                return
            
            room = self.rooms[room_id]
            file_id = request.get('file_id', '')
            
            if file_id not in room.files:
                self.send_response(client_socket, {
                    'status': 'error',
                    'message': 'File not found'
                })
                return
            
            file_info = room.files[file_id]
            file_path = os.path.join(room.room_dir, file_info['filename'])
            
            if not os.path.exists(file_path):
                self.send_response(client_socket, {
                    'status': 'error',
                    'message': 'File not found on disk'
                })
                return
            
            # Send file info response
            self.send_response(client_socket, {
                'status': 'success',
                'filename': file_info['name'],
                'file_size': file_info['size']
            })
            
            # Send file data
            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(8192)
                    if not chunk:
                        break
                    client_socket.send(chunk)
            
            logger.info(f"File downloaded: {file_info['name']} ({file_id}) from room {room.name}")
            
        except Exception as e:
            logger.error(f"Download error: {e}")
            self.send_response(client_socket, {
                'status': 'error',
                'message': 'Download failed'
            })
    
    def handle_delete_file(self, client_socket, request):
        """Handle file deletion"""
        try:
            # Check if client is in a room
            if client_socket not in self.client_rooms:
                self.send_response(client_socket, {
                    'status': 'error',
                    'message': 'Must join a room before deleting files'
                })
                return
            
            room_id = self.client_rooms[client_socket]
            if room_id not in self.rooms:
                self.send_response(client_socket, {
                    'status': 'error',
                    'message': 'Room not found'
                })
                return
            
            room = self.rooms[room_id]
            file_id = request.get('file_id', '')
            
            if file_id not in room.files:
                self.send_response(client_socket, {
                    'status': 'error',
                    'message': 'File not found'
                })
                return
            
            if room.remove_file(file_id):
                self.send_response(client_socket, {
                    'status': 'success',
                    'message': 'File deleted successfully'
                })
            else:
                self.send_response(client_socket, {
                    'status': 'error',
                    'message': 'Failed to delete file'
                })
                
        except Exception as e:
            logger.error(f"Delete file error: {e}")
            self.send_response(client_socket, {
                'status': 'error',
                'message': 'Delete failed'
            })
    
    def handle_list_files(self, client_socket, request):
        """Handle listing files"""
        try:
            # Check if client is in a room
            if client_socket not in self.client_rooms:
                self.send_response(client_socket, {
                    'status': 'success',
                    'files': []
                })
                return
            
            room_id = self.client_rooms[client_socket]
            if room_id not in self.rooms:
                self.send_response(client_socket, {
                    'status': 'success',
                    'files': []
                })
                return
            
            room = self.rooms[room_id]
            files = room.get_file_list()
            
            self.send_response(client_socket, {
                'status': 'success',
                'files': files
            })
            
        except Exception as e:
            logger.error(f"List files error: {e}")
            self.send_response(client_socket, {
                'status': 'error',
                'message': 'Failed to list files'
            })

def main():
    """Main server function"""
    print("Enhanced File Sharing Server v2.0")
    print("==================================")
    
    # Server configuration
    HOST = 'localhost'
    PORT = 8888
    
    try:
        server = FileServer(HOST, PORT)
        server.start_server()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        if 'server' in locals():
            server.stop_server()
    except Exception as e:
        print(f"Server error: {e}")
        logger.error(f"Server error: {e}")

if __name__ == "__main__":
    main()