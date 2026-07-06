import sys
import os
import uuid
import json
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLabel, QSystemTrayIcon, QMenu, QAction,
                             QFileDialog, QDialog, QTableWidget, QTableWidgetItem, QHeaderView,
                             QKeySequenceEdit, QDialogButtonBox, QComboBox, QMessageBox)
from PyQt5.QtCore import Qt, QPoint, QRect, QSize, pyqtSignal, QSettings
from PyQt5.QtGui import QPixmap, QPainter, QColor, QIcon, QCursor, QScreen, QGuiApplication, QKeyEvent, QKeySequence

# 导入全局热键模块
from PyQt5.QtCore import QAbstractNativeEventFilter, QAbstractEventDispatcher

# Windows系统下需要的库
import ctypes
from ctypes import wintypes
import win32con
import win32api
import win32gui

# 导入全局键盘和鼠标监听库
from pynput import keyboard, mouse
import threading

# 定义全局热键ID
TAKE_SCREENSHOT_HOTKEY_ID = 1

class WinEventFilter(QAbstractNativeEventFilter):
    """Windows事件过滤器，用于捕获全局热键"""
    def __init__(self, screenshot_tool):
        super().__init__()
        self.screenshot_tool = screenshot_tool
    
    def nativeEventFilter(self, eventType, message):
        # 处理Windows消息
        if eventType == "windows_generic_MSG":
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == win32con.WM_HOTKEY:
                if msg.wParam == TAKE_SCREENSHOT_HOTKEY_ID:
                    self.screenshot_tool.take_screenshot()
                    return True, 0
        return False, 0

# 添加一个隐藏窗口类，专门用于接收热键消息
class HotkeyWindow(QWidget):
    """隐藏窗口，专门用于接收全局热键"""
    def __init__(self, screenshot_tool, parent=None):
        super().__init__(parent, Qt.WindowFlags(Qt.Tool | Qt.FramelessWindowHint))
        self.screenshot_tool = screenshot_tool
        self.setGeometry(0, 0, 0, 0)  # 设置为0大小
        self.hide()  # 隐藏窗口
    
    def register_hotkey(self, key_str):
        """注册全局热键"""
        # 先尝试注销现有热键
        try:
            win32gui.UnregisterHotKey(int(self.winId()), TAKE_SCREENSHOT_HOTKEY_ID)
        except:
            pass
        
        # 解析快捷键
        modifiers, key = self.screenshot_tool.parse_key_sequence(key_str)
        
        if key != 0:
            # 注册新的全局热键
            try:
                result = win32gui.RegisterHotKey(int(self.winId()), TAKE_SCREENSHOT_HOTKEY_ID, modifiers, key)
                return result, None
            except Exception as e:
                return False, str(e)
        return False, "无效的按键"

class ScreenshotOverlay(QWidget):
    """截图覆盖层，用于选择截图区域"""
    # 定义信号
    screenshot_taken = pyqtSignal(QPixmap)
    screenshot_cancelled = pyqtSignal()
    
    def __init__(self, ctrl_triggered=False):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setWindowState(Qt.WindowFullScreen)
        self.setStyleSheet("background-color: rgba(0, 0, 0, 100);")
        
        # 截图区域的起始点和结束点
        self.begin = QPoint()
        self.end = QPoint()
        self.is_drawing = False
        
        # 是否由Ctrl+鼠标左键触发
        self.ctrl_triggered = ctrl_triggered
        
        # 捕获整个屏幕
        self.screen = QGuiApplication.primaryScreen()
        self.original_pixmap = self.screen.grabWindow(0)
        
        self.setCursor(Qt.CrossCursor)
        self.show()
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self.original_pixmap)
        
        # 绘制半透明遮罩
        painter.fillRect(0, 0, self.width(), self.height(), QColor(0, 0, 0, 100))
        
        if not self.is_drawing:
            return
            
        # 计算选择区域
        rect = QRect(self.begin, self.end).normalized()
        
        # 绘制选择区域（清除遮罩）
        selected_pixmap = self.original_pixmap.copy(rect)
        painter.drawPixmap(rect.topLeft(), selected_pixmap)
        
        # 绘制选择区域的边框
        pen = painter.pen()
        pen.setColor(QColor(0, 174, 255))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawRect(rect)
        
        # 在选择区域上方显示大小信息
        size_text = f"{rect.width()} × {rect.height()}"
        font = painter.font()
        font.setPointSize(10)
        painter.setFont(font)
        
        # 创建文本背景矩形
        text_rect = painter.boundingRect(QRect(), Qt.AlignLeft, size_text)
        text_rect.moveTopLeft(QPoint(rect.left(), rect.top() - text_rect.height() - 5))
        
        # 确保文本框不超出屏幕边界
        if text_rect.top() < 0:
            text_rect.moveTop(rect.bottom() + 5)
        if text_rect.right() > self.width():
            text_rect.moveRight(self.width() - 5)
        
        # 绘制文本背景
        painter.fillRect(text_rect, QColor(0, 0, 0, 160))
        
        # 绘制大小文本
        painter.setPen(Qt.white)
        painter.drawText(text_rect, Qt.AlignCenter, size_text)
        
        # 绘制放大镜效果（可选）
        if rect.width() > 10 and rect.height() > 10:
            # 在选区的四个角绘制小方块标记点
            square_size = 6
            painter.fillRect(rect.left() - square_size//2, rect.top() - square_size//2, 
                           square_size, square_size, QColor(0, 174, 255))
            painter.fillRect(rect.right() - square_size//2, rect.top() - square_size//2, 
                           square_size, square_size, QColor(0, 174, 255))
            painter.fillRect(rect.left() - square_size//2, rect.bottom() - square_size//2, 
                           square_size, square_size, QColor(0, 174, 255))
            painter.fillRect(rect.right() - square_size//2, rect.bottom() - square_size//2, 
                           square_size, square_size, QColor(0, 174, 255))
    
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.is_drawing = True
            self.begin = event.pos()
            self.end = event.pos()
            self.update()
    
    def mouseMoveEvent(self, event):
        if self.is_drawing:
            self.end = event.pos()
            self.update()
    
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.is_drawing:
            self.is_drawing = False
            self.end = event.pos()
            self.update()
            
            # 获取选择区域的截图
            rect = QRect(self.begin, self.end).normalized()
            if rect.width() > 10 and rect.height() > 10:  # 确保选择区域足够大
                screenshot = self.original_pixmap.copy(rect)
                self.hide()
                self.screenshot_taken.emit(screenshot)
            else:
                # 如果选择区域太小，取消截图
                self.hide()
                self.screenshot_cancelled.emit()
    
    def keyPressEvent(self, event):
        # 如果是Ctrl+鼠标左键触发的截图，忽略Ctrl键事件
        if self.ctrl_triggered and event.key() == Qt.Key_Control:
            event.accept()
            return
            
        # 按ESC取消截图
        if event.key() == Qt.Key_Escape:
            self.hide()
            self.screenshot_cancelled.emit()

    def keyReleaseEvent(self, event):
        # 如果是Ctrl+鼠标左键触发的截图，忽略Ctrl键事件
        if self.ctrl_triggered and event.key() == Qt.Key_Control:
            event.accept()
            return
        
        super().keyReleaseEvent(event)


class FloatingImage(QWidget):
    """浮动贴图窗口"""
    def __init__(self, pixmap, parent=None, shortcut_manager=None):
        super().__init__(parent)
        self.pixmap = pixmap
        self.original_pixmap = pixmap.copy()  # 保存原始图像副本
        self.id = str(uuid.uuid4())[:8]  # 生成唯一ID
        self.shortcut_manager = shortcut_manager  # 保存对快捷键管理器的引用
        
        # 设置窗口属性
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # 设置窗口大小为图像大小
        self.resize(pixmap.size())
        
        # 鼠标拖动相关变量
        self.dragging = False
        self.drag_position = QPoint()
        
        # 初始化悬停状态
        self.hover = False
        
        # 绘图相关变量
        self.drawing = False
        self.last_point = QPoint()
        self.current_tool = "move"  # 默认工具：移动
        self.pen_color = QColor(255, 0, 0)  # 默认红色画笔
        self.pen_width = 2  # 默认画笔宽度
        self.rect_start = QPoint()  # 矩形起始点
        self.ellipse_start = QPoint()  # 椭圆起始点
        self.mosaic_start = QPoint()  # 马赛克起始点
        self.mosaic_size = 10  # 马赛克块大小
        
        # 绘图历史
        self.drawing_history = []
        
        # 加载快捷键
        self.load_shortcuts()
        
        # 显示窗口
        self.show()
    
    def load_shortcuts(self):
        """加载快捷键设置"""
        if self.shortcut_manager:
            # 如果有快捷键管理器引用，使用它
            self.shortcuts = {
                "pen_tool": QKeySequence(self.shortcut_manager.get_shortcut("pen_tool")),
                "rect_tool": QKeySequence(self.shortcut_manager.get_shortcut("rect_tool")),
                "ellipse_tool": QKeySequence(self.shortcut_manager.get_shortcut("ellipse_tool")),
                "move_tool": QKeySequence(self.shortcut_manager.get_shortcut("move_tool")),
                "mosaic_tool": QKeySequence(self.shortcut_manager.get_shortcut("mosaic_tool")),
                "save_image": QKeySequence(self.shortcut_manager.get_shortcut("save_image")),
                "copy_image": QKeySequence(self.shortcut_manager.get_shortcut("copy_image")),
                "reset_image": QKeySequence(self.shortcut_manager.get_shortcut("reset_image"))
            }
        else:
            # 如果没有，从设置中加载
            settings = QSettings("ScreenshotTool", "Shortcuts")
            self.shortcuts = {
                "pen_tool": QKeySequence(settings.value("shortcuts/pen_tool", "Ctrl+P")),
                "rect_tool": QKeySequence(settings.value("shortcuts/rect_tool", "Ctrl+R")),
                "ellipse_tool": QKeySequence(settings.value("shortcuts/ellipse_tool", "Ctrl+E")),
                "move_tool": QKeySequence(settings.value("shortcuts/move_tool", "Ctrl+M")),
                "mosaic_tool": QKeySequence(settings.value("shortcuts/mosaic_tool", "Ctrl+K")),
                "save_image": QKeySequence(settings.value("shortcuts/save_image", "Ctrl+S")),
                "copy_image": QKeySequence(settings.value("shortcuts/copy_image", "Ctrl+C")),
                "reset_image": QKeySequence(settings.value("shortcuts/reset_image", "Ctrl+Z"))
            }
        
        # 安装事件过滤器以处理快捷键
        self.installEventFilter(self)
    
    def get_shortcut_string(self, action):
        """获取最新的快捷键字符串"""
        if self.shortcut_manager:
            return self.shortcut_manager.get_shortcut(action)
        else:
            settings = QSettings("ScreenshotTool", "Shortcuts")
            return settings.value(f"shortcuts/{action}", "")
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self.pixmap)
        
        # 绘制当前正在绘制的图形（如果有）
        if self.drawing:
            pen = painter.pen()
            pen.setColor(self.pen_color)
            pen.setWidth(self.pen_width)
            painter.setPen(pen)
            
            if self.current_tool == "rect":
                # 绘制矩形
                rect = QRect(self.rect_start, self.last_point).normalized()
                painter.drawRect(rect)
            elif self.current_tool == "ellipse":
                # 绘制椭圆
                rect = QRect(self.ellipse_start, self.last_point).normalized()
                painter.drawEllipse(rect)
            elif self.current_tool == "mosaic":
                # 绘制马赛克预览区域边框
                rect = QRect(self.mosaic_start, self.last_point).normalized()
                pen.setStyle(Qt.DashLine)  # 使用虚线
                painter.setPen(pen)
                painter.drawRect(rect)
        
        # 绘制边框（当鼠标悬停时）
        if self.hover:
            pen = painter.pen()
            pen.setColor(QColor(0, 174, 255))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawRect(0, 0, self.width()-1, self.height()-1)
    
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.current_tool == "move":
                # 移动模式
                self.dragging = True
                self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
            elif self.current_tool == "pen":
                # 画笔模式
                self.drawing = True
                self.last_point = event.pos()
            elif self.current_tool == "rect":
                # 矩形模式
                self.drawing = True
                self.rect_start = event.pos()
                self.last_point = event.pos()
            elif self.current_tool == "ellipse":
                # 椭圆模式
                self.drawing = True
                self.ellipse_start = event.pos()
                self.last_point = event.pos()
            elif self.current_tool == "mosaic":
                # 马赛克模式
                self.drawing = True
                self.mosaic_start = event.pos()
                self.last_point = event.pos()
            event.accept()
    
    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            if self.current_tool == "move" and self.dragging:
                # 移动模式
                self.move(event.globalPos() - self.drag_position)
            elif self.current_tool == "pen" and self.drawing:
                # 画笔模式
                painter = QPainter(self.pixmap)
                pen = painter.pen()
                pen.setColor(self.pen_color)
                pen.setWidth(self.pen_width)
                painter.setPen(pen)
                painter.drawLine(self.last_point, event.pos())
                self.last_point = event.pos()
                self.update()
                # 保存绘图历史
                self.drawing_history.append(("pen", self.last_point, event.pos(), self.pen_color, self.pen_width))
            elif (self.current_tool == "rect" or self.current_tool == "ellipse" or self.current_tool == "mosaic") and self.drawing:
                # 矩形、椭圆或马赛克模式（预览）
                self.last_point = event.pos()
                self.update()
            event.accept()
    
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.current_tool == "move":
                self.dragging = False
            elif self.current_tool == "pen":
                self.drawing = False
            elif self.current_tool == "rect" and self.drawing:
                # 绘制最终矩形
                painter = QPainter(self.pixmap)
                pen = painter.pen()
                pen.setColor(self.pen_color)
                pen.setWidth(self.pen_width)
                painter.setPen(pen)
                rect = QRect(self.rect_start, event.pos()).normalized()
                painter.drawRect(rect)
                self.update()
                # 保存绘图历史
                self.drawing_history.append(("rect", self.rect_start, event.pos(), self.pen_color, self.pen_width))
                self.drawing = False
            elif self.current_tool == "ellipse" and self.drawing:
                # 绘制最终椭圆
                painter = QPainter(self.pixmap)
                pen = painter.pen()
                pen.setColor(self.pen_color)
                pen.setWidth(self.pen_width)
                painter.setPen(pen)
                rect = QRect(self.ellipse_start, event.pos()).normalized()
                painter.drawEllipse(rect)
                self.update()
                # 保存绘图历史
                self.drawing_history.append(("ellipse", self.ellipse_start, event.pos(), self.pen_color, self.pen_width))
                self.drawing = False
            elif self.current_tool == "mosaic" and self.drawing:
                # 应用马赛克效果
                rect = QRect(self.mosaic_start, event.pos()).normalized()
                if rect.width() > 5 and rect.height() > 5:  # 确保选择区域足够大
                    self.apply_mosaic(rect)
                    self.update()
                    # 保存绘图历史
                    self.drawing_history.append(("mosaic", self.mosaic_start, event.pos(), self.mosaic_size))
                self.drawing = False
    
    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.close()
    
    def enterEvent(self, event):
        self.hover = True
        self.update()
    
    def leaveEvent(self, event):
        self.hover = False
        self.update()
    
    def contextMenuEvent(self, event):
        menu = QMenu(self)
        
        # 工具操作直接放在主菜单中，实时获取快捷键
        move_action = QAction(f"移动 ({self.get_shortcut_string('move_tool')})", self)
        move_action.triggered.connect(lambda: self.set_tool("move"))
        move_action.setCheckable(True)
        move_action.setChecked(self.current_tool == "move")
        
        pen_action = QAction(f"画笔 ({self.get_shortcut_string('pen_tool')})", self)
        pen_action.triggered.connect(lambda: self.set_tool("pen"))
        pen_action.setCheckable(True)
        pen_action.setChecked(self.current_tool == "pen")
        
        rect_action = QAction(f"矩形 ({self.get_shortcut_string('rect_tool')})", self)
        rect_action.triggered.connect(lambda: self.set_tool("rect"))
        rect_action.setCheckable(True)
        rect_action.setChecked(self.current_tool == "rect")
        
        ellipse_action = QAction(f"椭圆 ({self.get_shortcut_string('ellipse_tool')})", self)
        ellipse_action.triggered.connect(lambda: self.set_tool("ellipse"))
        ellipse_action.setCheckable(True)
        ellipse_action.setChecked(self.current_tool == "ellipse")
        
        mosaic_action = QAction(f"马赛克 ({self.get_shortcut_string('mosaic_tool')})", self)
        mosaic_action.triggered.connect(lambda: self.set_tool("mosaic"))
        mosaic_action.setCheckable(True)
        mosaic_action.setChecked(self.current_tool == "mosaic")
        
        # 颜色子菜单
        color_menu = QMenu("颜色", self)
        
        red_action = QAction("红色", self)
        red_action.triggered.connect(lambda: self.set_color(QColor(255, 0, 0)))
        
        green_action = QAction("绿色", self)
        green_action.triggered.connect(lambda: self.set_color(QColor(0, 255, 0)))
        
        blue_action = QAction("蓝色", self)
        blue_action.triggered.connect(lambda: self.set_color(QColor(0, 0, 255)))
        
        black_action = QAction("黑色", self)
        black_action.triggered.connect(lambda: self.set_color(QColor(0, 0, 0)))
        
        color_menu.addAction(red_action)
        color_menu.addAction(green_action)
        color_menu.addAction(blue_action)
        color_menu.addAction(black_action)
        
        # 马赛克块大小子菜单
        mosaic_size_menu = QMenu("马赛克大小", self)
        
        small_action = QAction("小 (5像素)", self)
        small_action.triggered.connect(lambda: self.set_mosaic_size(5))
        
        medium_action = QAction("中 (10像素)", self)
        medium_action.triggered.connect(lambda: self.set_mosaic_size(10))
        
        large_action = QAction("大 (15像素)", self)
        large_action.triggered.connect(lambda: self.set_mosaic_size(15))
        
        xlarge_action = QAction("超大 (20像素)", self)
        xlarge_action.triggered.connect(lambda: self.set_mosaic_size(20))
        
        mosaic_size_menu.addAction(small_action)
        mosaic_size_menu.addAction(medium_action)
        mosaic_size_menu.addAction(large_action)
        mosaic_size_menu.addAction(xlarge_action)
        
        # 基本操作
        copy_action = QAction(f"复制 ({self.get_shortcut_string('copy_image')})", self)
        copy_action.triggered.connect(self.copy_to_clipboard)
        
        save_action = QAction(f"保存 ({self.get_shortcut_string('save_image')})", self)
        save_action.triggered.connect(self.save_image)
        
        reset_action = QAction(f"重置图像 ({self.get_shortcut_string('reset_image')})", self)
        reset_action.triggered.connect(self.reset_image)
        
        close_action = QAction("关闭", self)
        close_action.triggered.connect(self.close)
        
        # 添加所有菜单项
        menu.addAction(move_action)
        menu.addAction(pen_action)
        menu.addAction(rect_action)
        menu.addAction(ellipse_action)
        menu.addAction(mosaic_action)
        menu.addSeparator()
        menu.addMenu(color_menu)
        menu.addMenu(mosaic_size_menu)
        menu.addSeparator()
        menu.addAction(copy_action)
        menu.addAction(save_action)
        menu.addAction(reset_action)
        menu.addSeparator()
        menu.addAction(close_action)
        
        menu.exec_(event.globalPos())
    
    def copy_to_clipboard(self):
        clipboard = QApplication.clipboard()
        clipboard.setPixmap(self.pixmap)
    
    def save_image(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "保存图片", os.path.expanduser("~/Pictures/screenshot.png"),
            "PNG图片 (*.png);;JPEG图片 (*.jpg *.jpeg);;所有文件 (*.*)"
        )
        
        if file_path:
            self.pixmap.save(file_path)
    
    def set_tool(self, tool):
        """设置当前工具"""
        self.current_tool = tool
        # 根据工具设置鼠标样式
        if tool == "move":
            self.setCursor(Qt.ArrowCursor)
        elif tool in ["pen", "rect", "ellipse", "mosaic"]:
            self.setCursor(Qt.CrossCursor)
    
    def set_color(self, color):
        """设置画笔颜色"""
        self.pen_color = color
    
    def reset_image(self):
        """重置图像到原始状态"""
        self.pixmap = self.original_pixmap.copy()
        self.drawing_history.clear()
        self.update()
    
    def eventFilter(self, obj, event):
        """事件过滤器，用于处理快捷键"""
        if event.type() == QKeyEvent.KeyPress:
            key_event = QKeyEvent(event)
            key = key_event.key()
            modifiers = key_event.modifiers()
            
            # 创建当前按下的键序列
            key_seq = QKeySequence(modifiers | key)
            
            # 检查是否匹配各种快捷键
            if key_seq.matches(self.shortcuts["pen_tool"]) == QKeySequence.ExactMatch:
                self.set_tool("pen")
                return True
            elif key_seq.matches(self.shortcuts["rect_tool"]) == QKeySequence.ExactMatch:
                self.set_tool("rect")
                return True
            elif key_seq.matches(self.shortcuts["ellipse_tool"]) == QKeySequence.ExactMatch:
                self.set_tool("ellipse")
                return True
            elif key_seq.matches(self.shortcuts["move_tool"]) == QKeySequence.ExactMatch:
                self.set_tool("move")
                return True
            elif key_seq.matches(self.shortcuts["mosaic_tool"]) == QKeySequence.ExactMatch:
                self.set_tool("mosaic")
                return True
            elif key_seq.matches(self.shortcuts["save_image"]) == QKeySequence.ExactMatch:
                self.save_image()
                return True
            elif key_seq.matches(self.shortcuts["copy_image"]) == QKeySequence.ExactMatch:
                self.copy_to_clipboard()
                return True
            elif key_seq.matches(self.shortcuts["reset_image"]) == QKeySequence.ExactMatch:
                self.reset_image()
                return True
        
        return super().eventFilter(obj, event)

    def apply_mosaic(self, rect):
        """在选定区域应用马赛克效果"""
        # 获取选定区域的图像
        selected_pixmap = self.pixmap.copy(rect)
        
        # 创建一个临时QImage来处理像素
        image = selected_pixmap.toImage()
        width = image.width()
        height = image.height()
        
        # 根据马赛克块大小计算网格
        for x in range(0, width, self.mosaic_size):
            for y in range(0, height, self.mosaic_size):
                # 取块的左上角像素颜色
                pixel_color = image.pixelColor(x, y)
                
                # 填充整个块
                for dx in range(min(self.mosaic_size, width - x)):
                    for dy in range(min(self.mosaic_size, height - y)):
                        image.setPixelColor(x + dx, y + dy, pixel_color)
        
        # 将处理后的图像应用回pixmap
        processed_pixmap = QPixmap.fromImage(image)
        
        # 将处理后的pixmap绘制到原图相应位置
        painter = QPainter(self.pixmap)
        painter.drawPixmap(rect.topLeft(), processed_pixmap)
        painter.end()

    def set_mosaic_size(self, size):
        """设置马赛克块大小"""
        self.mosaic_size = size


class ShortcutManager:
    """快捷键管理类"""
    def __init__(self):
        self.settings = QSettings("ScreenshotTool", "Shortcuts")
        self.default_shortcuts = {
            "take_screenshot": "Ctrl+Alt+A",
            "pen_tool": "Ctrl+P",
            "rect_tool": "Ctrl+R",
            "ellipse_tool": "Ctrl+E",
            "move_tool": "Ctrl+M",
            "mosaic_tool": "Ctrl+K",  # 添加马赛克工具的默认快捷键
            "save_image": "Ctrl+S",
            "copy_image": "Ctrl+C",
            "reset_image": "Ctrl+Z"
        }
        self.load_shortcuts()
    
    def load_shortcuts(self):
        """从设置加载快捷键"""
        self.shortcuts = {}
        for action, default in self.default_shortcuts.items():
            key_str = self.settings.value(f"shortcuts/{action}", default)
            self.shortcuts[action] = key_str
    
    def save_shortcuts(self):
        """保存快捷键到设置"""
        for action, key_str in self.shortcuts.items():
            self.settings.setValue(f"shortcuts/{action}", key_str)
    
    def get_shortcut(self, action):
        """获取指定操作的快捷键"""
        return self.shortcuts.get(action, "")
    
    def set_shortcut(self, action, key_str):
        """设置指定操作的快捷键"""
        self.shortcuts[action] = key_str
        self.save_shortcuts()
    
    def reset_to_defaults(self):
        """重置所有快捷键为默认值"""
        self.shortcuts = self.default_shortcuts.copy()
        self.save_shortcuts()


class ShortcutDialog(QDialog):
    """快捷键设置对话框"""
    def __init__(self, shortcut_manager, parent=None):
        super().__init__(parent)
        self.shortcut_manager = shortcut_manager
        self.parent_tool = parent  # 保存父窗口引用
        self.setWindowTitle("编辑快捷键")
        self.setMinimumWidth(400)
        self.initUI()
        
    def closeEvent(self, event):
        """处理窗口关闭事件"""
        # 隐藏窗口而不是关闭
        event.ignore()
        self.hide()
    
    def initUI(self):
        layout = QVBoxLayout(self)
        
        # 创建表格
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["操作", "快捷键"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        layout.addWidget(self.table)
        
        # 填充表格
        self.populate_table()
        
        # 按钮
        button_layout = QHBoxLayout()
        reset_btn = QPushButton("重置为默认")
        reset_btn.clicked.connect(self.reset_shortcuts)
        
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        
        button_layout.addWidget(reset_btn)
        button_layout.addWidget(button_box)
        layout.addLayout(button_layout)
    
    def populate_table(self):
        """填充快捷键表格"""
        action_names = {
            "take_screenshot": "截图",
            "pen_tool": "画笔工具",
            "rect_tool": "矩形工具",
            "ellipse_tool": "椭圆工具",
            "move_tool": "移动工具",
            "mosaic_tool": "马赛克工具",  # 添加马赛克工具的名称
            "save_image": "保存图像",
            "copy_image": "复制图像",
            "reset_image": "重置图像"
        }
        
        self.table.setRowCount(len(self.shortcut_manager.shortcuts))
        for i, (action, key_str) in enumerate(self.shortcut_manager.shortcuts.items()):
            # 操作名称
            name_item = QTableWidgetItem(action_names.get(action, action))
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)  # 设为不可编辑
            name_item.setData(Qt.UserRole, action)  # 存储操作ID
            self.table.setItem(i, 0, name_item)
            
            # 快捷键编辑器
            key_edit = QKeySequenceEdit(QKeySequence(key_str))
            self.table.setCellWidget(i, 1, key_edit)
    
    def accept(self):
        """保存修改的快捷键"""
        # 前一次的快捷键
        old_screenshot_shortcut = self.shortcut_manager.get_shortcut("take_screenshot")
        
        # 收集新快捷键
        for i in range(self.table.rowCount()):
            action = self.table.item(i, 0).data(Qt.UserRole)
            key_edit = self.table.cellWidget(i, 1)
            key_str = key_edit.keySequence().toString()
            self.shortcut_manager.set_shortcut(action, key_str)
        
        # 检查截图快捷键是否更改
        new_screenshot_shortcut = self.shortcut_manager.get_shortcut("take_screenshot")
        
        # 如果截图快捷键有变化，并且父窗口存在
        if old_screenshot_shortcut != new_screenshot_shortcut and hasattr(self, 'parent_tool') and self.parent_tool:
            # 先注销旧的热键
            try:
                win32gui.UnregisterHotKey(int(self.parent_tool.hotkey_window.winId()), TAKE_SCREENSHOT_HOTKEY_ID)
            except Exception as e:
                print(f"注销旧热键错误: {str(e)}")
            
            # 重新注册新的热键
            self.parent_tool.register_hotkey()
            
            # 更新所有浮动图像的快捷键
            for image in self.parent_tool.floating_images:
                image.load_shortcuts()
            
            # 更新托盘菜单
            self.parent_tool.update_tray_menu()
            
            self.parent_tool.status_label.setText(f'快捷键已更新为: {new_screenshot_shortcut}')
        
        # 隐藏对话框而不是关闭
        self.hide()
        # 发送接受信号但不关闭窗口
        self.accepted.emit()
    
    def reject(self):
        """取消修改快捷键"""
        # 隐藏对话框而不是关闭
        self.hide()
        # 发送拒绝信号但不关闭窗口
        self.rejected.emit()
    
    def reset_shortcuts(self):
        """重置所有快捷键为默认值"""
        self.shortcut_manager.reset_to_defaults()
        self.populate_table()


# 添加键盘和鼠标监听类
class KeyMouseListener:
    """监听全局键盘和鼠标事件的类"""
    def __init__(self, screenshot_tool):
        self.screenshot_tool = screenshot_tool
        self.ctrl_pressed = False
        self.running = False
        self.keyboard_listener = None
        self.mouse_listener = None
    
    def start(self):
        """开始监听键盘和鼠标事件"""
        if self.running:
            return
        
        self.running = True
        self.ctrl_pressed = False
        
        # 创建并启动键盘监听器
        self.keyboard_listener = keyboard.Listener(
            on_press=self.on_key_press,
            on_release=self.on_key_release)
        
        # 创建并启动鼠标监听器
        self.mouse_listener = mouse.Listener(
            on_click=self.on_mouse_click)
        
        # 在单独的线程中启动监听器
        self.keyboard_listener.start()
        self.mouse_listener.start()
    
    def stop(self):
        """停止监听键盘和鼠标事件"""
        if not self.running:
            return
        
        self.running = False
        
        # 停止键盘监听器
        if self.keyboard_listener:
            self.keyboard_listener.stop()
            self.keyboard_listener = None
        
        # 停止鼠标监听器
        if self.mouse_listener:
            self.mouse_listener.stop()
            self.mouse_listener = None
    
    def on_key_press(self, key):
        """键盘按下事件处理"""
        try:
            # 检查是否按下Ctrl键
            if key == keyboard.Key.ctrl or key == keyboard.Key.ctrl_l or key == keyboard.Key.ctrl_r:
                self.ctrl_pressed = True
        except AttributeError:
            pass
    
    def on_key_release(self, key):
        """键盘释放事件处理"""
        try:
            # 检查是否释放Ctrl键
            if key == keyboard.Key.ctrl or key == keyboard.Key.ctrl_l or key == keyboard.Key.ctrl_r:
                self.ctrl_pressed = False
        except AttributeError:
            pass
    
    def on_mouse_click(self, x, y, button, pressed):
        """鼠标点击事件处理"""
        if pressed and button == mouse.Button.left and self.ctrl_pressed:
            # 当按下Ctrl键的同时点击鼠标左键时，触发截图
            # 使用线程安全的方式调用截图函数
            QApplication.instance().postEvent(self.screenshot_tool, 
                QKeyEvent(QKeyEvent.KeyPress, Qt.Key_F24, Qt.NoModifier))


class ScreenshotTool(QMainWindow):
    """主应用窗口"""
    def __init__(self):
        super().__init__()
        self.shortcut_manager = ShortcutManager()
        self.initUI()
        self.floating_images = []  # 存储所有浮动贴图窗口
        self.setup_global_hotkeys()
        
        # 创建并启动键盘鼠标监听器
        self.key_mouse_listener = KeyMouseListener(self)
        self.key_mouse_listener.start()
        
        # 安装事件过滤器以处理特殊按键
        self.installEventFilter(self)
    
    def initUI(self):
        self.setWindowTitle('贴图工具')
        self.setGeometry(100, 100, 300, 200)
        
        # 创建中央窗口部件和布局
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        # 创建截图按钮
        self.screenshot_btn = QPushButton('截图', self)
        self.screenshot_btn.clicked.connect(self.take_screenshot)
        layout.addWidget(self.screenshot_btn)
        
        # 创建快捷键设置按钮
        self.shortcut_btn = QPushButton('编辑快捷键', self)
        self.shortcut_btn.clicked.connect(self.edit_shortcuts)
        layout.addWidget(self.shortcut_btn)
        
        # 创建状态标签
        self.status_label = QLabel('准备就绪', self)
        layout.addWidget(self.status_label)
        
        # 创建系统托盘图标
        self.tray_icon = QSystemTrayIcon(self)
        # 优先加载同目录下的截图.png作为托盘图标
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '截图.png')
        if os.path.exists(icon_path):
            icon = QIcon(icon_path)
            self.tray_icon.setIcon(icon)
        else:
            self.tray_icon.setIcon(self.style().standardIcon(QApplication.style().SP_ComputerIcon))
        
        # 创建托盘菜单
        tray_menu = QMenu()
        
        # 获取快捷键字符串
        screenshot_shortcut = self.shortcut_manager.get_shortcut("take_screenshot")
        
        screenshot_action = QAction(f'截图 ({screenshot_shortcut})', self)
        screenshot_action.triggered.connect(self.take_screenshot)
        
        shortcut_action = QAction('编辑快捷键', self)
        shortcut_action.triggered.connect(self.edit_shortcuts)
        
        quit_action = QAction('退出', self)
        quit_action.triggered.connect(self.quit_application)
        
        tray_menu.addAction(screenshot_action)
        tray_menu.addAction(shortcut_action)
        tray_menu.addSeparator()
        tray_menu.addAction(quit_action)
        
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()
        
        # 连接托盘图标的激活信号
        self.tray_icon.activated.connect(self.on_tray_activated)
    
    def on_tray_activated(self, reason):
        """处理托盘图标激活事件"""
        if reason == QSystemTrayIcon.DoubleClick:
            self.show()
    
    def setup_global_hotkeys(self):
        """设置全局热键"""
        # 创建隐藏窗口用于接收热键
        self.hotkey_window = HotkeyWindow(self)
        
        # 安装事件过滤器
        self.win_event_filter = WinEventFilter(self)
        self.event_dispatcher = QAbstractEventDispatcher.instance()
        self.event_dispatcher.installNativeEventFilter(self.win_event_filter)
        
        # 注册全局热键
        self.register_hotkey()
    
    def parse_key_sequence(self, key_str):
        """将QKeySequence字符串转换为Windows热键"""
        modifiers = 0
        key = 0
        
        key_seq = QKeySequence(key_str)
        if not key_seq.isEmpty():
            key_combo = key_seq[0]
            
            # 解析修饰键
            if key_combo & int(Qt.ControlModifier):
                modifiers |= win32con.MOD_CONTROL
            if key_combo & int(Qt.AltModifier):
                modifiers |= win32con.MOD_ALT
            if key_combo & int(Qt.ShiftModifier):
                modifiers |= win32con.MOD_SHIFT
            if key_combo & int(Qt.MetaModifier):
                modifiers |= win32con.MOD_WIN
            
            # 提取主键 - 修复类型错误
            mask = int(Qt.ControlModifier) | int(Qt.AltModifier) | int(Qt.ShiftModifier) | int(Qt.MetaModifier)
            key = key_combo & ~mask
            
            # 将Qt键码转换为Windows虚拟键码
            if key >= Qt.Key_A and key <= Qt.Key_Z:
                key = ord(chr(key - Qt.Key_A + ord('A')))
            elif key >= Qt.Key_0 and key <= Qt.Key_9:
                key = ord(chr(key - Qt.Key_0 + ord('0')))
            elif key == Qt.Key_Space:
                key = win32con.VK_SPACE
            # 常用功能键映射
            elif key == Qt.Key_F1:
                key = win32con.VK_F1
            elif key == Qt.Key_F2:
                key = win32con.VK_F2
            elif key == Qt.Key_F3:
                key = win32con.VK_F3
            elif key == Qt.Key_F4:
                key = win32con.VK_F4
            elif key == Qt.Key_F5:
                key = win32con.VK_F5
            elif key == Qt.Key_F6:
                key = win32con.VK_F6
            elif key == Qt.Key_F7:
                key = win32con.VK_F7
            elif key == Qt.Key_F8:
                key = win32con.VK_F8
            elif key == Qt.Key_F9:
                key = win32con.VK_F9
            elif key == Qt.Key_F10:
                key = win32con.VK_F10
            elif key == Qt.Key_F11:
                key = win32con.VK_F11
            elif key == Qt.Key_F12:
                key = win32con.VK_F12
        
        return modifiers, key
    
    def register_hotkey(self):
        """注册全局热键"""
        # 获取截图快捷键
        key_str = self.shortcut_manager.get_shortcut("take_screenshot")
        
        # 使用隐藏窗口注册热键
        result, error = self.hotkey_window.register_hotkey(key_str)
        
        if result:
            self.status_label.setText(f'全局热键已注册: {key_str}')
            # 更新托盘菜单显示的快捷键
            self.update_tray_menu()
        else:
            error_msg = error if error else "未知错误"
            self.status_label.setText(f'全局热键注册失败: {error_msg}')
    
    def update_tray_menu(self):
        """更新托盘菜单中显示的快捷键"""
        screenshot_shortcut = self.shortcut_manager.get_shortcut("take_screenshot")
        
        # 创建新的托盘菜单
        tray_menu = QMenu()
        
        screenshot_action = QAction(f'截图 ({screenshot_shortcut})', self)
        screenshot_action.triggered.connect(self.take_screenshot)
        
        shortcut_action = QAction('编辑快捷键', self)
        shortcut_action.triggered.connect(self.edit_shortcuts)
        
        quit_action = QAction('退出', self)
        quit_action.triggered.connect(self.quit_application)
        
        tray_menu.addAction(screenshot_action)
        tray_menu.addAction(shortcut_action)
        tray_menu.addSeparator()
        tray_menu.addAction(quit_action)
        
        # 更新托盘图标的菜单
        self.tray_icon.setContextMenu(tray_menu)
    
    def take_screenshot(self, ctrl_triggered=False):
        """开始截图过程"""
        self.hide()  # 隐藏主窗口
        
        # 延迟一小段时间，确保窗口完全隐藏
        QApplication.processEvents()
        
        # 创建截图覆盖层
        self.overlay = ScreenshotOverlay(ctrl_triggered=ctrl_triggered)
        self.overlay.screenshot_taken.connect(self.on_screenshot_taken)
        self.overlay.screenshot_cancelled.connect(self.on_screenshot_cancelled)
    
    def on_screenshot_taken(self, pixmap):
        """处理截图完成事件"""
        # 创建新的浮动贴图窗口，传入shortcut_manager
        floating_image = FloatingImage(pixmap, shortcut_manager=self.shortcut_manager)
        self.floating_images.append(floating_image)
        
        # 更新状态标签，但不显示主窗口
        self.status_label.setText(f'已创建贴图 #{floating_image.id}')
        # 不再调用 self.show()
    
    def on_screenshot_cancelled(self):
        """处理截图取消事件"""
        self.status_label.setText('截图已取消')
        # 不再调用 self.show()
    
    def edit_shortcuts(self):
        """打开快捷键编辑对话框"""
        dialog = ShortcutDialog(self.shortcut_manager, self)
        # 不再在这里手动调用register_hotkey，而是在ShortcutDialog的accept方法中处理
        dialog.exec_()
    
    def closeEvent(self, event):
        """处理窗口关闭事件"""
        # 最小化到系统托盘而不是关闭
        event.ignore()
        self.hide()
        self.tray_icon.showMessage('贴图工具', '应用已最小化到系统托盘', QSystemTrayIcon.Information, 2000)
    
    def quit_application(self):
        """真正退出应用程序"""
        # 注销全局热键 (使用隐藏窗口的winId)
        try:
            win32gui.UnregisterHotKey(int(self.hotkey_window.winId()), TAKE_SCREENSHOT_HOTKEY_ID)
        except:
            pass
        
        # 停止键盘鼠标监听器
        if hasattr(self, 'key_mouse_listener'):
            self.key_mouse_listener.stop()
        
        # 关闭所有浮动图像窗口
        for image in self.floating_images:
            image.close()
        # 退出应用
        QApplication.quit()

    def eventFilter(self, obj, event):
        """事件过滤器，处理特殊按键事件"""
        if event.type() == QKeyEvent.KeyPress:
            key_event = QKeyEvent(event)
            key = key_event.key()
            
            # F24键是从KeyMouseListener发送的特殊按键，表示Ctrl+鼠标左键被按下
            if key == Qt.Key_F24:
                self.take_screenshot(ctrl_triggered=True)
                return True
        
        return super().eventFilter(obj, event)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    tool = ScreenshotTool()
    tool.show()
    sys.exit(app.exec_())