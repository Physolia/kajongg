"""
Copyright (c) 2007-2008 Qtrac Ltd <mark@qtrac.eu>
Copyright (C) 2008-2016 Wolfgang Rohdewald <wolfgang@rohdewald.de>

SPDX-License-Identifier: GPL-2.0

"""

from qt import Qt, QSize, QRect, QEvent
from qt import QStyledItemDelegate, QLabel, QTextDocument, QStyle, QPalette, \
    QStyleOptionViewItem, QApplication

from guiutil import Painter


class ZeroEmptyColumnDelegate(QStyledItemDelegate):

    """Display 0 or 0.00 as empty"""

    def displayText(self, value, locale):
        """Display 0 or 0.00 as empty"""
        if isinstance(value, int) and value == 0:
            return ''
        if isinstance(value, float) and value == 0.0:
            return ''
        return super().displayText(value, locale)

class RichTextColumnDelegate(QStyledItemDelegate):

    """enables rich text in a view"""
    label = None
    document = None

    def __init__(self, parent=None):
        super().__init__(parent)
        if self.label is None:
            self.label = QLabel()
            self.label.setIndent(5)
            self.label.setTextFormat(Qt.RichText)
            self.document = QTextDocument()

    def paint(self, painter, option, index):
        """paint richtext"""
        if option.state & QStyle.State_Selected:
            role = QPalette.Highlight
        else:
            role = QPalette.AlternateBase if index.row() % 2 else QPalette.Base
        self.label.setBackgroundRole(role)
        text = index.model().data(index, Qt.DisplayRole)
        self.label.setText(text)
        self.label.setFixedSize(option.rect.size())
        with Painter(painter):
            painter.translate(option.rect.topLeft())
            self.label.render(painter)

    def sizeHint(self, option, index):
        """compute size for the final formatted richtext"""
        text = index.model().data(index)
        self.document.setDefaultFont(option.font)
        self.document.setHtml(text)
        return QSize(int(self.document.idealWidth()) + 5,
                     option.fontMetrics.height())


class RightAlignedCheckboxDelegate(QStyledItemDelegate):

    """as the name says. From
https://wiki.qt.io/Technical_FAQ#How_can_I_align_the_checkboxes_in_a_view.3F"""

    def __init__(self, parent, cellFilter):
        super().__init__(parent)
        self.cellFilter = cellFilter

    @staticmethod
    def __textMargin():
        """text margin"""
        return QApplication.style().pixelMetric(
            QStyle.PM_FocusFrameHMargin) + 1

    def paint(self, painter, option, index):
        """paint right aligned checkbox"""
        viewItemOption = QStyleOptionViewItem(option)
        if self.cellFilter(index):
            textMargin = self.__textMargin()
            newRect = QStyle.alignedRect(
                option.direction, Qt.AlignRight,
                QSize(
                    option.decorationSize.width() + 5,
                    option.decorationSize.height()),
                QRect(
                    option.rect.x() + textMargin, option.rect.y(),
                    option.rect.width() - (2 * textMargin),
                    option.rect.height()))
            viewItemOption.rect = newRect
        QStyledItemDelegate.paint(self, painter, viewItemOption, index)

    def editorEvent(self, event, model, option, index):
        """edit right aligned checkbox"""
        flags = model.flags(index)
        # make sure that the item is checkable
        if not flags & Qt.ItemIsUserCheckable or not flags & Qt.ItemIsEnabled:
            return False
        # make sure that we have a check state
        value = index.data(Qt.CheckStateRole)
        if not isinstance(value, int):
            return False
        # make sure that we have the right event type
        if event.type() == QEvent.MouseButtonRelease:
            textMargin = self.__textMargin()
            checkRect = QStyle.alignedRect(
                option.direction, Qt.AlignRight,
                option.decorationSize,
                QRect(
                    option.rect.x() + (2 * textMargin), option.rect.y(),
                    option.rect.width() - (2 * textMargin),
                    option.rect.height()))
            if not checkRect.contains(event.pos()):
                return False
        elif event.type() == QEvent.KeyPress:
            if event.key() not in (Qt.Key_Space, Qt.Key_Select):
                return False
        else:
            return False
        if value == Qt.Checked:
            state = Qt.Unchecked
        else:
            state = Qt.Checked
        return model.setData(index, state, Qt.CheckStateRole)
