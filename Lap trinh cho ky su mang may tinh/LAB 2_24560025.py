import sys
from PyQt5.QtWidgets import (QApplication, QMainWindow, QAction, QFileDialog, 
                           QStatusBar, QTabWidget, QMessageBox, QPlainTextEdit)
from PyQt5.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal

# FileLoader: Reads file chunks in the background using QRunnable
class FileLoaderSignals(QObject):
    chunk_loaded = pyqtSignal(str, int, int)  # Emits chunk, start, and end positions
    loading_finished = pyqtSignal()  # Emits when no more data to load

class FileLoader(QRunnable):
    def __init__(self, filename, chunk_size, start_pos, end_pos):
        super().__init__()
        self.filename = filename
        self.chunk_size = chunk_size
        self.start_pos = start_pos
        self.end_pos = end_pos
        self.signals = FileLoaderSignals()

    def run(self):
        try:
            with open(self.filename, 'rb') as f:  # Read the file in binary mode
                f.seek(self.start_pos)
                chunk_bytes = f.read(self.chunk_size)  # Read exactly chunk_size bytes
                if chunk_bytes:
                    # Decode the file using utf-8, ignoring invalid sequences
                    chunk = chunk_bytes.decode('utf-8', errors='ignore')
                    self.end_pos = self.start_pos + len(chunk_bytes)  # Determine the exact byte position
                    if chunk:
                        self.signals.chunk_loaded.emit(chunk, self.start_pos, self.end_pos)
                    else:
                        self.signals.loading_finished.emit()
                else:
                    self.signals.loading_finished.emit()
        except Exception as e:
            print(f"Error loading file: {e}")

# Indicates a text edit that loads file content in chunks
class LazyTextEdit(QPlainTextEdit):
    chunk_appended = pyqtSignal()
    def __init__(self, parent=None):
        super().__init__(parent)
        self.thread_pool = QThreadPool(self)  # Thread pool for loading file chunks in the background
        self.thread_pool.setMaxThreadCount(5)  # Limit concurrent threads
        self.filename = None
        self.chunk_size = 50000  # 50 KB chunks
        self.start_pos = 0
        self.end_pos = self.chunk_size
        self.loading_done = False
        self.verticalScrollBar().valueChanged.connect(self.handle_scroll)

    def load_file(self, filename):
        self.filename = filename
        self.clear()
        self.start_pos = 0
        self.end_pos = self.chunk_size
        self.loading_done = False
        self.load_next_chunk()

    def load_next_chunk(self):
        if self.loading_done:
            return
        loader = FileLoader(self.filename, self.chunk_size, self.start_pos, self.end_pos)
        loader.signals.chunk_loaded.connect(self.append_chunk)
        loader.signals.loading_finished.connect(self.set_loading_done)
        self.thread_pool.start(loader)

    def append_chunk(self, text, start_pos, end_pos):
        cursor = self.textCursor()
        print(f"Appending chunk from {start_pos} to {end_pos}") #Check if the start and end positions are correct
        cursor.movePosition(cursor.End)
        cursor.insertText(text)
        self.start_pos = end_pos
        self.end_pos = self.start_pos + self.chunk_size
        self.chunk_appended.emit()

    def set_loading_done(self):
        self.loading_done = True

    def handle_scroll(self, value):
        if not self.loading_done:
            scroll_bar = self.verticalScrollBar()
            if value >= scroll_bar.maximum():
                self.load_next_chunk()

# Notepad: Main application window
class Notepad(QMainWindow):
    def __init__(self):
        super().__init__()
        self.initUI()

    def initUI(self):
        self.setWindowTitle('Notepad thread handle')
        self.setGeometry(500, 200, 1080, 800)

        # Set up tab widget for multiple documents
        self.tabWidget = QTabWidget(self)
        self.tabWidget.setTabsClosable(True)
        self.tabWidget.currentChanged.connect(self.updateWordCount)
        self.tabWidget.tabCloseRequested.connect(self.closeTab)
        self.setCentralWidget(self.tabWidget)

        # Add initial empty tab
        self.addNewTab()

        # Set up status bar for word count
        self.statusBar = QStatusBar(self)
        self.setStatusBar(self.statusBar)
        self.updateWordCount()

        # Create File menu
        menubar = self.menuBar()
        fileMenu = menubar.addMenu('Choose your file')
        newAction = QAction('New', self)
        newAction.triggered.connect(self.addNewTab)
        fileMenu.addAction(newAction)
        openAction = QAction('Open', self)
        openAction.triggered.connect(self.openFile)
        fileMenu.addAction(openAction)
        saveAction = QAction('Save', self)
        saveAction.triggered.connect(self.saveFile)
        fileMenu.addAction(saveAction)
        saveAsAction = QAction('Save As', self)
        saveAsAction.triggered.connect(self.saveAsFile)
        fileMenu.addAction(saveAsAction)

        self.showMaximized()

    def addNewTab(self):
        textEdit = LazyTextEdit()
        index = self.tabWidget.addTab(textEdit, f'Untitled-{self.tabWidget.count() + 1}')
        self.tabWidget.setCurrentIndex(index)
        textEdit.textChanged.connect(self.updateWordCount)
        self.updateWordCount()

    def updateWordCount(self):
        currentTextEdit = self.tabWidget.currentWidget()
        if currentTextEdit and isinstance(self.statusBar, QStatusBar):
            text = currentTextEdit.toPlainText()
            words = len(text.split())
            self.statusBar.showMessage(f'Words: {words}')

    def openFile(self):
        fname, _ = QFileDialog.getOpenFileName(self, 'Open File', '', 'Text Files (*.txt)')
        if fname:
            try:
                textEdit = LazyTextEdit()
                index = self.tabWidget.addTab(textEdit, fname.split('/')[-1])
                self.tabWidget.setCurrentIndex(index)
                textEdit.textChanged.connect(self.updateWordCount)
                textEdit.chunk_appended.connect(self.updateWordCount)
                textEdit.load_file(fname)
                textEdit.filename = fname
                self.updateWordCount()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not open file: {e}")

    def saveFile(self):
        currentTextEdit = self.tabWidget.currentWidget()
        if currentTextEdit:
            if hasattr(currentTextEdit, 'filename') and currentTextEdit.filename:
                try:
                    with open(currentTextEdit.filename, 'w', encoding='utf-8') as f:
                        f.write(currentTextEdit.toPlainText())
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Could not save file: {e}")
            else:
                self.saveAsFile()
            self.updateWordCount()

    def saveAsFile(self):
        currentTextEdit = self.tabWidget.currentWidget()
        if currentTextEdit:
            fname, _ = QFileDialog.getSaveFileName(self, 'Save As', '', 'Text Files (*.txt)')
            if fname:
                try:
                    with open(fname, 'w', encoding='utf-8') as f:
                        f.write(currentTextEdit.toPlainText())
                    currentTextEdit.filename = fname
                    self.tabWidget.setTabText(self.tabWidget.currentIndex(), fname.split('/')[-1])
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Could not save file: {e}")
            self.updateWordCount()

    def closeTab(self, index):
        textEdit = self.tabWidget.widget(index)
        if textEdit and textEdit.toPlainText():
            if not hasattr(textEdit, 'filename') or not textEdit.filename:
                response = QMessageBox.warning(
                    self, "Warning",
                    "You have unsaved changes. Save before closing the tab?",
                    QMessageBox.Yes | QMessageBox.No
                )
                if response == QMessageBox.No:
                    return
        self.tabWidget.removeTab(index)
        if isinstance(self.statusBar, QStatusBar):
            self.updateWordCount()

    def closeEvent(self, event):
        currentTextEdit = self.tabWidget.currentWidget()
        if currentTextEdit and currentTextEdit.toPlainText():
            if not hasattr(currentTextEdit, 'filename') or not currentTextEdit.filename:
                response = QMessageBox.warning(self, "Warning", 
                    "You have unsaved changes. Do you want to save before closing?",
                    QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
                if response == QMessageBox.Yes:
                    self.saveFile()
                elif response == QMessageBox.Cancel:
                    event.ignore()
                    return
        event.accept()
    

# Start the application
if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = Notepad()
    app.exec_()
