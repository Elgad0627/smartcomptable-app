# -*- coding: utf-8 -*-
"""SmartComptable Pro - Система умной бухгалтерии для Франции и Швеции
Версия: 2.7 (Для веб-размещения, с функцией удаления, без OCR/PDF)
"""

# Настройка страницы ПЕРВЫМ ДЕЛОМ
import streamlit as st
st.set_page_config(page_title="SmartComptable Pro",
                   page_icon="🇫🇷🇸🇪",
                   layout="wide",
                   initial_sidebar_state="expanded")

# - Импорты -
import pandas as pd
import os
import json
import re
from datetime import datetime, timedelta
import sqlite3
from pathlib import Path
import hashlib
import base64
from PIL import Image
import numpy as np
from typing import Dict, List, Optional, Tuple
import plotly.express as px
import plotly.graph_objects as go
from dataclasses import dataclass, asdict
import locale
import calendar
import time
import secrets
import tempfile

# - Импорт для работы с куками -
import extra_streamlit_components as stx

# - Условные импорты с обработкой ошибок -

# bcrypt для хеширования паролей администратора
try:
    import bcrypt
    BCRYPT_AVAILABLE = True
except ImportError:
    st.warning("⚠️ bcrypt не найден - используем MockBcrypt (НЕ для продакшена)")
    BCRYPT_AVAILABLE = False


# - Отключаем OCR и PDF -
# Tesseract OCR для извлечения текста из изображений
TESSERACT_AVAILABLE = False # <-- Отключено для веб-версии

# pdfplumber для извлечения текста из PDF
PDFPLUMBER_AVAILABLE = False # <-- Отключено для веб-версии

# openai для ИИ-классификации (опционально)
try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    st.info("ℹ️ openai не найден - ИИ-классификация будет недоступна")
    OPENAI_AVAILABLE = False

# - Структуры данных -
@dataclass
class ExpenseRecord:
    """Структура данных для записи расходов"""
    id: str
    date: str
    amount: float
    supplier: str
    category: str
    description: str
    file_path: str
    siret: Optional[str] = None
    tva_rate: float = 20.0
    validated: bool = False
    created_at: Optional[str] = None

# - Менеджеры данных -
class DatabaseManager:
    """Менеджер базы данных SQLite для хранения расходов и пользователей"""
    def __init__(self, db_path: str = "smartcomptable_pro.db"):
        self.db_path = db_path
        self.init_database()

    def init_database(self):
        """Инициализация базы данных и таблиц"""
        print("DEBUG: Initializing database...")
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Таблица расходов
        cursor.execute('''CREATE TABLE IF NOT EXISTS expenses (
            id TEXT PRIMARY KEY,
            date TEXT NOT NULL,
            amount REAL NOT NULL,
            supplier TEXT NOT NULL,
            category TEXT NOT NULL,
            description TEXT,
            file_path TEXT,
            siret TEXT,
            tva_rate REAL DEFAULT 20.0,
            validated INTEGER DEFAULT 1,
            created_at TEXT
        )''')
        
        # Таблица пользователей/подписок
        cursor.execute('''CREATE TABLE IF NOT EXISTS subscriptions (
            email TEXT PRIMARY KEY,
            subscription_end TEXT,
            is_admin INTEGER DEFAULT 0
        )''')
        
        # Таблица категорий (для будущего расширения)
        cursor.execute('''CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name_fr TEXT UNIQUE NOT NULL,
            name_se TEXT UNIQUE NOT NULL
        )''')
        
        # Добавление стандартных категорий, если их нет
        default_categories = [
            ('Fournitures', 'Förbrukningsmaterial'),
            ('Salaire', 'Lön'),
            ('Location', 'Hyra'),
            ('Électricité', 'El'),
            ('Internet', 'Internet'),
            ('Assurance', 'Försäkring'),
            ('Marketing', 'Marknadsföring'),
            ('Maintenance', 'Underhåll'),
            ('Transport', 'Transport'),
            ('Autre', 'Övrigt')
        ]
        
        for cat_fr, cat_se in default_categories:
            cursor.execute(
                'INSERT OR IGNORE INTO categories (name_fr, name_se) VALUES (?, ?)',
                (cat_fr, cat_se)
            )
        
        conn.commit()
        conn.close()
        print("DEBUG: Database initialized successfully")

    def add_expense(self, expense: ExpenseRecord) -> bool:
        """Добавление новой записи о расходе в базу данных"""
        print(f"DEBUG: DatabaseManager.add_expense called for {expense.id}")
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            # Убедитесь, что количество ? совпадает с количеством полей и указано поле id
            cursor.execute('''INSERT INTO expenses (id, date, amount, supplier, category, description,
                           file_path, siret, tva_rate, validated, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', 
                           (expense.id, expense.date, expense.amount, expense.supplier,
                            expense.category, expense.description, expense.file_path,
                            expense.siret, expense.tva_rate, expense.validated, expense.created_at))
            conn.commit()
            print(f"DEBUG: Expense {expense.id} saved successfully with file path {expense.file_path}")
            return True
        except Exception as e:
            print(f"DEBUG: Error saving expense {expense.id}: {e}")
            if conn:
                conn.rollback()
            return False
        finally:
            if conn:
                conn.close()

    def get_expenses(self, year: Optional[int] = None) -> List[ExpenseRecord]:
        """Получение всех записей о расходах, опционально за определенный год"""
        print(f"DEBUG: DatabaseManager.get_expenses called for year {year}")
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            if year:
                query = '''SELECT * FROM expenses 
                          WHERE strftime('%Y', date) = ? 
                          ORDER BY date DESC'''
                cursor.execute(query, (str(year),))
            else:
                query = 'SELECT * FROM expenses ORDER BY date DESC'
                cursor.execute(query)
            
            rows = cursor.fetchall()
            print(f"DEBUG: Executing query: {query} with params: {(str(year),) if year else ()}")
            print(f"DEBUG: Fetched {len(rows)} expenses from DB")
            
            expenses = []
            for row in rows:
                expense = ExpenseRecord(
                    id=row[0],
                    date=row[1],
                    amount=row[2],
                    supplier=row[3],
                    category=row[4],
                    description=row[5],
                    file_path=row[6],
                    siret=row[7],
                    tva_rate=row[8],
                    validated=bool(row[9]),
                    created_at=row[10]
                )
                expenses.append(expense)
            
            print(f"DEBUG: Successfully created {len(expenses)} expense objects")
            return expenses
        except Exception as e:
            print(f"DEBUG: Error fetching expenses: {e}")
            return []
        finally:
            if conn:
                conn.close()
            print("DEBUG: DB connection for fetching closed.")

    def get_categories(self, lang: str = 'fr') -> List[str]:
        """Получение списка категорий на выбранном языке"""
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            column = 'name_fr' if lang == 'fr' else 'name_se'
            cursor.execute(f'SELECT {column} FROM categories ORDER BY {column}')
            categories = [row[0] for row in cursor.fetchall()]
            return categories
        except Exception as e:
            print(f"DEBUG: Error fetching categories: {e}")
            # Возврат стандартных категорий в случае ошибки
            return ['Fournitures', 'Salaire', 'Location'] if lang == 'fr' else ['Förbrukningsmaterial', 'Lön', 'Hyra']
        finally:
            if conn:
                conn.close()

    # Добавляем метод удаления записей
    def delete_expense(self, expense_id: str) -> bool:
        """
        Удаление записи о расходе по ID.
        Возвращает True, если запись была найдена и удалена, иначе False.
        """
        print(f"DEBUG: DatabaseManager.delete_expense called for expense ID {expense_id}")
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            # Выполняем удаление
            cursor.execute('DELETE FROM expenses WHERE id = ?', (expense_id,))
            rows_affected = cursor.rowcount  # Количество удаленных строк
            conn.commit()
            if rows_affected > 0:
                print(f"DEBUG: Expense {expense_id} deleted successfully")
                return True
            else:
                print(f"DEBUG: No expense found with ID {expense_id} to delete")
                return False
        except Exception as e:
            print(f"DEBUG: Error deleting expense {expense_id}: {e}")
            # st.error(f"Erreur lors de la suppression: {e}")  # Можно показать ошибку пользователю
            if conn:
                conn.rollback()  # Откатываем изменения в случае ошибки
            return False
        finally:
            if conn:
                conn.close()


class DocumentProcessor:
    """Обработчик документов для извлечения текста и данных"""
    
    def __init__(self):
        self.tesseract_available = TESSERACT_AVAILABLE
        self.pdfplumber_available = PDFPLUMBER_AVAILABLE
    
    def extract_text_from_image(self, image_path: str) -> str:
        """Извлечение текста из изображения с помощью Tesseract OCR"""
        # if not self.tesseract_available:
        return "OCR недоступен - Tesseract не установлен или отключен для веб-версии"
        
        # ... (остальной код OCR, который не будет выполняться) ...
    
    def extract_text_from_pdf(self, pdf_path: str) -> str:
        """Извлечение текста из PDF с помощью pdfplumber"""
        # if not self.pdfplumber_available:
        return "Поддержка PDF недоступна - pdfplumber не установлен или отключен для веб-версии"
        
        # ... (остальной код PDF, который не будет выполняться) ...
    
    def extract_data_from_text(self, text: str, lang: str = 'fr') -> Dict:
        """Извлечение данных (дата, сумма, поставщик) из текста"""
        # Для веб-версии это не используется, так как OCR/PDF отключены.
        # Возвращаем пустой словарь или заглушки.
        return {
            'date': datetime.now().strftime('%Y-%m-%d'),
            'amount': 0.0,
            'supplier': "Fournisseur à saisir",
            'category': "Autre" if lang == 'fr' else "Övrigt",
            'siret': None,
            'tva_rate': 20.0
        }
    
    # Остальные методы поиска данных (find_date, find_amount и т.д.) остаются,
    # но они не будут вызываться, так как extract_text_* возвращают сообщения об ошибке.
    # Для полноты картины их можно оставить.

class AIClassifier:
    """Классификатор категорий с использованием ИИ (если доступно)"""
    
    def __init__(self, openai_api_key: Optional[str] = None):
        self.ai_available = OPENAI_AVAILABLE and openai_api_key
        if self.ai_available:
            openai.api_key = openai_api_key
    
    def classify_expense(self, description: str, amount: float, supplier: str, lang: str = 'fr') -> str:
        """Классификация расхода на категорию с помощью ИИ или правил"""
        # Если ИИ недоступен, используем простые правила
        return self._rule_based_classification(description, amount, supplier, lang)
    
    def _rule_based_classification(self, description: str, amount: float, supplier: str, lang: str) -> str:
        """Классификация на основе простых правил"""
        # Простая заглушка для веб-версии
        return 'Autre' if lang == 'fr' else 'Övrigt'

# - Функции интерфейса -
def get_text(key: str, lang: str) -> str:
    """Получение перевода текста по ключу"""
    translations = {
        'app_title': {
            'fr': "🇫🇷 SmartComptable Pro - Comptabilité Intelligente",
            'se': "🇸🇪 SmartComptable Pro - Intelligent Bokföring"
        },
        'app_subtitle': {
            'fr': "Votre assistant de comptabilité automatisé pour la France",
            'se': "Din automatiserade bokföringsassistent för Sverige"
        },
        'navigation': {
            'fr': "🧭 Navigation",
            'se': "🧭 Navigation"
        },
        'choose_page': {
            'fr': "Choisissez une page",
            'se': "Välj sida"
        },
        'import_docs': {
            'fr': "📤 Importer des Documents",
            'se': "📤 Importera Dokument"
        },
        'dashboard': {
            'fr': "📊 Tableau de Bord",
            'se': "📊 Instrumentpanel"
        },
        'reports': {
            'fr': "📈 Rapports",
            'se': "📈 Rapporter"
        },
        'settings': {
            'fr': "⚙️ Paramètres",
            'se': "⚙️ Inställningar"
        },
        'admin': {
            'fr': "👑 Administration",
            'se': "👑 Administration"
        },
        'logout': {
            'fr': "🚪 Déconnexion",
            'se': "🚪 Logga ut"
        },
        'language': {
            'fr': "Langue",
            'se': "Språk"
        },
        'save': {
            'fr': "💾 Enregistrer",
            'se': "💾 Spara"
        },
        'date': {
            'fr': "📅 Date",
            'se': "📅 Datum"
        },
        'amount': {
            'fr': "💰 Montant (€)",
            'se': "💰 Belopp (kr)"
        },
        'supplier': {
            'fr': "🏢 Fournisseur",
            'se': "🏢 Leverantör"
        },
        'category': {
            'fr': "🏷️ Catégorie",
            'se': "🏷️ Kategori"
        },
        'description': {
            'fr': "📝 Description",
            'se': "📝 Beskrivning"
        },
        'tva_rate': {
            'fr': "📊 Taux de TVA (%)",
            'se': "📊 Moms (%)"
        },
        'processing': {
            'fr': "Traitement en cours...",
            'se': "Bearbetar..."
        },
        'manual_entry': {
            'fr': "Saisie manuelle requise",
            'se': "Manuell inmatning krävs"
        },
        'no_expenses': {
            'fr': "Aucune dépense enregistrée pour le moment.",
            'se': "Inga utgifter registrerade ännu."
        },
        'enter_email': {
            'fr': "Veuillez entrer votre email",
            'se': "Vänligen ange din e-post"
        },
        'activate_test': {
            'fr': "Activer le mode test (30 jours)",
            'se': "Aktivera testläge (30 dagar)"
        },
        'email': {
            'fr': "📧 Email",
            'se': "📧 E-post"
        },
        'test_mode': {
            'fr': "🧪 Mode Test",
            'se': "🧪 Testläge"
        },
        'subscription_expired': {
            'fr': "Votre abonnement a expiré. Veuillez renouveler.",
            'se': "Din prenumeration har gått ut. Vänligen förnya."
        },
        'subscription_valid_until': {
            'fr': "Votre abonnement est valide jusqu'au",
            'se': "Din prenumeration är giltig till"
        },
        'renew_subscription': {
            'fr': "Renouveler l'abonnement",
            'se': "Förnya prenumeration"
        }
    }
    
    return translations.get(key, {}).get(lang, f"[{key}]")

# - Исправленный код для работы с куками -
def initialize_cookie_manager():
    """Инициализировать и сохранить менеджер куков в st.session_state."""
    if 'cookie_manager' not in st.session_state:
        st.session_state.cookie_manager = stx.CookieManager(key="smartcomptable_cookies_unique_v2")

def set_auth_cookie(email: str, days_expire: int = 30):
    """Установить куку аутентификации."""
    # Создаем уникальный ключ для куки
    # cookie_key = "smartcomptable_auth"
    # Устанавливаем куку на указанное количество дней
    expire_date = datetime.now() + timedelta(days=days_expire)
    
    # Сохраняем email и время истечения в куке (новый формат)
    cookie_value = f"{email}|{expire_date.isoformat()}"
    # Убеждаемся, что менеджер инициализирован
    initialize_cookie_manager()
    # Используем менеджер из st.session_state
    st.session_state.cookie_manager.set(cookie="smartcomptable_auth", val=cookie_value, expires_at=expire_date, key="set_auth_cookie_v2")
    print(f"DEBUG: Auth cookie set for {email}, expires {expire_date}")

def get_auth_cookie() -> Optional[str]:
    """Получить email из куки аутентификации, если она действительна."""
    # cookie_key = "smartcomptable_auth"
    try:
        # Убеждаемся, что менеджер инициализирован
        initialize_cookie_manager()
        # Получаем все куки из менеджера в st.session_state
        cookies = st.session_state.cookie_manager.get_all()
        if cookies is None:
            cookies = {}
        auth_cookie = cookies.get("smartcomptable_auth")
        # print(f"DEBUG: Raw auth cookie value: {auth_cookie}") # Для отладки
        
        if auth_cookie:
            try:
                email, expire_str = auth_cookie.split("|", 1)
                expire_date = datetime.fromisoformat(expire_str)
                if datetime.now() < expire_date:
                    return email
                else:
                    # Кука истекла, удаляем её
                    st.session_state.cookie_manager.delete("smartcomptable_auth", key="delete_expired_cookie_v2")
                    print(f"DEBUG: Кука для {email} истекла и была удалена.")
            except (ValueError, TypeError) as e:
                # Неверный формат куки
                print(f"DEBUG: Ошибка разбора куки: {e}")
                pass
        else:
            print("DEBUG: No auth cookie found")
            return None
    except Exception as e:
        print(f"DEBUG: Error getting auth cookie: {e}")
        return None

def delete_auth_cookie():
    """Удалить куку аутентификации."""
    # cookie_key = "smartcomptable_auth"
    try:
        # Убеждаемся, что менеджер инициализирован
        initialize_cookie_manager()
        st.session_state.cookie_manager.delete("smartcomptable_auth", key="delete_cookie_v2")
        print("DEBUG: Auth cookie deleted")
    except Exception as e:
        print(f"DEBUG: Error deleting auth cookie: {e}")

# - Менеджер подписок -
class SubscriptionManager:
    """Менеджер подписок пользователей"""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
    
    def is_subscribed(self, email: str) -> bool:
        """Проверить, действует ли подписка у пользователя"""
        conn = None
        try:
            conn = sqlite3.connect(self.db_manager.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT subscription_end FROM subscriptions WHERE email = ?', (email,))
            row = cursor.fetchone()
            if row and row[0]:
                end_date = datetime.fromisoformat(row[0])
                return datetime.now() < end_date
            return False
        except Exception as e:
            print(f"DEBUG: Error checking subscription for {email}: {e}")
            return False
        finally:
            if conn:
                conn.close()
    
    def get_subscription_end_date(self, email: str) -> Optional[datetime]:
        """Получить дату окончания подписки"""
        conn = None
        try:
            conn = sqlite3.connect(self.db_manager.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT subscription_end FROM subscriptions WHERE email = ?', (email,))
            row = cursor.fetchone()
            if row and row[0]:
                return datetime.fromisoformat(row[0])
            return None
        except Exception as e:
            print(f"DEBUG: Error getting subscription end date for {email}: {e}")
            return None
        finally:
            if conn:
                conn.close()
    
    def grant_free_subscription(self, email: str, days: int = 30, granted_by_admin: bool = True) -> bool:
        """Предоставить бесплатную подписку на определенное количество дней"""
        conn = None
        try:
            conn = sqlite3.connect(self.db_manager.db_path)
            cursor = conn.cursor()
            
            # Вычисляем дату окончания подписки
            end_date = datetime.now() + timedelta(days=days)
            
            # Вставляем или обновляем запись о подписке
            cursor.execute('''INSERT OR REPLACE INTO subscriptions 
                           (email, subscription_end, is_admin) 
                           VALUES (?, ?, ?)''', 
                           (email, end_date.isoformat(), 1 if granted_by_admin else 0))
            
            conn.commit()
            print(f"DEBUG: Free subscription granted to {email} for {days} days (admin: {granted_by_admin})")
            return True
        except Exception as e:
            print(f"DEBUG: Error granting subscription to {email}: {e}")
            if conn:
                conn.rollback()
            return False
        finally:
            if conn:
                conn.close()
    
    def add_admin(self, email: str) -> bool:
        """Добавить администратора"""
        conn = None
        try:
            conn = sqlite3.connect(self.db_manager.db_path)
            cursor = conn.cursor()
            
            # Проверяем, существует ли пользователь
            cursor.execute('SELECT email FROM subscriptions WHERE email = ?', (email,))
            if cursor.fetchone():
                # Обновляем существующего пользователя как администратора
                cursor.execute('UPDATE subscriptions SET is_admin = 1 WHERE email = ?', (email,))
            else:
                # Создаем нового администратора (без подписки)
                cursor.execute('INSERT INTO subscriptions (email, is_admin) VALUES (?, 1)', (email,))
            
            conn.commit()
            print(f"DEBUG: Admin rights granted to {email}")
            return True
        except Exception as e:
            print(f"DEBUG: Error adding admin {email}: {e}")
            if conn:
                conn.rollback()
            return False
        finally:
            if conn:
                conn.close()
    
    def is_admin(self, email: str) -> bool:
        """Проверить, является ли пользователь администратором"""
        conn = None
        try:
            conn = sqlite3.connect(self.db_manager.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT is_admin FROM subscriptions WHERE email = ?', (email,))
            row = cursor.fetchone()
            return bool(row and row[0])
        except Exception as e:
            print(f"DEBUG: Error checking admin status for {email}: {e}")
            return False
        finally:
            if conn:
                conn.close()

# - Менеджер аутентификации -
class AuthManager:
    """Менеджер аутентификации пользователей"""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        # Для демонстрации используем фиксированный пароль администратора
        # В реальном приложении используйте bcrypt
        self.admin_password_hash = self._hash_password(b"admin123")
    
    def _hash_password(self, password: bytes) -> bytes:
        """Хеширование пароля"""
        if BCRYPT_AVAILABLE:
            return bcrypt.hashpw(password, bcrypt.gensalt())
        else:
            # Mock хеширование для демонстрации
            import secrets
            salt = secrets.token_bytes(16)
            # ВАЖНО: Это НЕ безопасный способ для продакшена. Используйте настоящий bcrypt.
            # Для демонстрации используем пароль + соль + статический ключ
            combined = password + b"demo_salt_key_2024" + salt
            return base64.b64encode(hashlib.sha256(combined).digest() + salt)
    
    @staticmethod
    def gensalt() -> bytes:
        return secrets.token_bytes(16)
    
    @staticmethod
    def checkpw(password: bytes, hashed: bytes) -> bool:
        try:
            if BCRYPT_AVAILABLE:
                return bcrypt.checkpw(password, hashed)
            else:
                # Mock проверка для демонстрации
                # Декодируем хеш из base64
                decoded_hash = base64.b64decode(hashed)
                # Извлекаем "соль" (последние 16 байт)
                salt = decoded_hash[-16:]
                # Вычисляем хеш с использованием извлеченной соли
                combined = password + b"demo_salt_key_2024" + salt
                computed_hash = hashlib.sha256(combined).digest()
                # Сравниваем только хеш-часть (первые 32 байта)
                return decoded_hash[:32] == computed_hash
        except:
            return False
    
    def authenticate_admin(self, password: str) -> bool:
        """Аутентификация администратора"""
        return self.checkpw(password.encode('utf-8'), self.admin_password_hash)

# - Страницы приложения -
def show_dashboard_page(lang: str):
    """Главная страница с дашбордом"""
    st.header(get_text('dashboard', lang))
    db_manager = st.session_state.db_manager
    current_year = datetime.now().year
    currency = "€" if lang == 'fr' else "kr"
    
    # Получение данных
    expenses = db_manager.get_expenses(current_year)
    print(f"DEBUG: Dashboard получил {len(expenses)} расходов для {current_year} года")
    
    if not expenses:
        st.info(get_text('no_expenses', lang))
        return
    
    # Преобразование в DataFrame для анализа
    df = pd.DataFrame([{
        'date': exp.date,
        'amount': exp.amount,
        'supplier': exp.supplier,
        'category': exp.category
    } for exp in expenses])
    
    df['date'] = pd.to_datetime(df['date'])
    df['month'] = df['date'].dt.month
    df['year'] = df['date'].dt.year
    
    # Метрики
    col1, col2, col3 = st.columns(3)
    total_expenses = df['amount'].sum()
    avg_expense = df['amount'].mean()
    expense_count = len(df)
    
    col1.metric("💸 Dépenses totales" if lang == 'fr' else "💸 Totala utgifter", 
                f"{total_expenses:.2f} {currency}")
    col2.metric("📊 Moyenne par dépense" if lang == 'fr' else "📊 Genomsnitt per utgift", 
                f"{avg_expense:.2f} {currency}")
    col3.metric("🧮 Nombre de dépenses" if lang == 'fr' else "🧮 Antal utgifter", 
                expense_count)
    
    # Графики
    st.subheader("📈 Analyse des dépenses" if lang == 'fr' else "📈 Utgiftsanalys")
    
    # График расходов по месяцам
    monthly_expenses = df.groupby('month')['amount'].sum().reindex(range(1, 13), fill_value=0)
    fig_monthly = px.line(x=monthly_expenses.index, y=monthly_expenses.values,
                         labels={'x': 'Mois' if lang == 'fr' else 'Månad', 
                                'y': f'Montant ({currency})' if lang == 'fr' else f'Belopp ({currency})'},
                         title='Dépenses mensuelles' if lang == 'fr' else 'Månadsutgifter')
    st.plotly_chart(fig_monthly, use_container_width=True)
    
    # График расходов по категориям
    category_expenses = df.groupby('category')['amount'].sum().sort_values(ascending=False)
    fig_category = px.pie(values=category_expenses.values, names=category_expenses.index,
                         title='Répartition par catégorie' if lang == 'fr' else 'Fördelning per kategori')
    st.plotly_chart(fig_category, use_container_width=True)
    
    # Последние операции
    st.subheader("🕒 Dernières Opérations" if lang == 'fr' else "🕒 Senaste Transaktioner")
    recent_expenses = expenses[:10]  # Последние 10
    
    if recent_expenses:
        # Вместо одной общей таблицы, создаем expander для каждой записи
        for i, expense in enumerate(recent_expenses):
            # Создаем уникальный ключ для expander, используя ID записи для надежности
            with st.expander(f"📅 {expense.date} - {expense.supplier} - {expense.amount:.2f} {currency}", expanded=False):
                col1, col2 = st.columns(2)
                with col1:
                    st.write(f"**{'Date' if lang != 'fr' else 'Date'}:** {expense.date}")
                    st.write(f"**{'Fournisseur' if lang == 'fr' else 'Leverantör'}:** {expense.supplier}")
                    st.write(f"**{'Catégorie' if lang == 'fr' else 'Kategori'}:** {expense.category}")
                    st.write(f"**{'Montant' if lang == 'fr' else 'Belopp'}:** {expense.amount:.2f} {currency}")
                    st.write(f"**{'TVA' if lang == 'fr' else 'Moms'}:** {expense.tva_rate}%")
                    # st.write(f"**Description:** {expense.description}")  # Можно добавить, если нужно

                with col2:
                    # Кнопка редактирования (пока заглушка)
                    # if st.button("📝 Modifier", key=f"edit_{expense.id}"):
                    #     st.info("La fonction d'édition sera implémentée prochainement.")

                    # --- Кнопка УДАЛЕНИЯ ---
                    if st.button("🗑️ Supprimer", key=f"delete_{expense.id}"):
                        # Вызываем метод удаления из DatabaseManager
                        db_manager = st.session_state.db_manager  # Получаем db_manager из состояния сессии
                        if db_manager.delete_expense(expense.id):
                            st.success("✅ Dépense supprimée avec succès!" if lang == 'fr' else "✅ Utgift borttagen!")
                            # !!! ВАЖНО: Перезагружаем страницу, чтобы обновить список !!!
                            st.rerun()  # или time.sleep(1); st.rerun()
                        else:
                            st.error("❌ Erreur lors de la suppression" if lang == 'fr' else "❌ Fel vid borttagning")
    else:
        st.info(get_text('no_expenses', lang))

def show_import_page(lang: str):
    """Страница импорта документов"""
    st.header(get_text('import_docs', lang))
    db_manager = st.session_state.db_manager
    doc_processor = DocumentProcessor()
    
    # Загрузка файлов
    uploaded_files = st.file_uploader(
        "📄 Choisissez des images (JPG, PNG) ou des PDF", 
        type=['jpg', 'jpeg', 'png', 'pdf'],
        accept_multiple_files=True
    )
    
    if uploaded_files:
        for uploaded_file in uploaded_files:
            st.subheader(f"📄 {uploaded_file.name}")
            
            # Создание временного файла
            with tempfile.NamedTemporaryFile(delete=False, suffix=Path(uploaded_file.name).suffix) as tmp_file:
                tmp_file.write(uploaded_file.getvalue())
                file_path = Path(tmp_file.name)
            
            temp_file_name = file_path.name  # Для уникальных ключей элементов
            
            try:
                # --- 1. Отображение загруженного файла ---
                if uploaded_file.type.startswith('image'):
                    image = Image.open(uploaded_file)
                    st.image(image, caption=get_text('processing', lang), use_column_width=True)
                elif uploaded_file.type == "application/pdf":
                    st.info("📄 PDF загружен. Обработка...")
                
                # --- 2. Извлечение текста из файла ---
                # В веб-версии OCR и PDF отключены, поэтому сразу показываем форму ручного ввода.
                # Но для совместимости с логикой, вызываем методы, которые вернут сообщение об ошибке.
                with st.spinner(get_text('processing', lang)):
                    text = ""
                    try:
                        if uploaded_file.type == "application/pdf":
                            text = doc_processor.extract_text_from_pdf(str(file_path))
                        elif uploaded_file.type.startswith('image'):
                            text = doc_processor.extract_text_from_image(str(file_path))
                        print(f"DEBUG: Извлеченный текст (первые 100 символов): {text[:100] if text else 'None'}")
                    except Exception as e:
                        st.error(f"❌ Ошибка обработки файла {uploaded_file.name}: {e}")
                        text = ""
                
                # --- 3. Анализ извлеченного текста и форма ввода данных ---
                # Поскольку OCR/PDF отключены, text будет сообщением об ошибке.
                # Поэтому сразу переходим к ручному вводу.
                # if text and not text.startswith(("Ошибка", "OCR недоступен", "Поддержка PDF недоступна")) and len(text.strip()) > 5:
                #     ... (код автоматического извлечения - УДАЛЕН)
                # else:
                # - 5. Форма ручного ввода, если OCR не удался или текст не найден -
                st.warning(get_text('manual_entry', lang) + " (OCR/PDF отключены)")
                st.subheader("✏️ Saisie manuelle")
                
                col1, col2 = st.columns(2)
                with col1:
                    date = st.date_input(get_text("date", lang), datetime.now().date(), key=f"manual_date_{temp_file_name}")
                    amount = st.number_input(get_text("amount", lang), min_value=0.01, value=0.01, step=0.01, key=f"manual_amount_{temp_file_name}")
                    supplier = st.text_input(get_text("supplier", lang), key=f"manual_supplier_{temp_file_name}")
                
                with col2:
                    categories = db_manager.get_categories(lang)
                    category = st.selectbox(get_text("category", lang), categories, key=f"manual_category_{temp_file_name}")
                    tva_rate = st.number_input(get_text("tva_rate", lang), min_value=0.0, max_value=100.0, value=20.0, step=0.1, key=f"manual_tva_{temp_file_name}")
                    description = st.text_input(get_text("description", lang), value=uploaded_file.name, key=f"manual_desc_{temp_file_name}")
                
                if st.button(get_text("save", lang) + f" manuellement - {uploaded_file.name}", key=f"manual_save_{temp_file_name}"):
                    if amount > 0 and supplier.strip():
                        # Создание уникального ID с временной меткой
                        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
                        expense_id = hashlib.md5(f"{date}{amount}{supplier}{timestamp}".encode()).hexdigest()[:8]
                        
                        expense = ExpenseRecord(
                            id=expense_id,
                            date=date.strftime('%Y-%m-%d'),
                            amount=amount,
                            supplier=supplier,
                            category=category,
                            description=description,
                            file_path=str(file_path),  # Сохраняем путь к файлу
                            tva_rate=float(tva_rate),
                            validated=True
                        )
                        
                        if db_manager.add_expense(expense):
                            st.success("✅ Dépense enregistrée avec succès!")
                            # time.sleep(1)
                            # st.rerun()
                        else:
                            st.error("❌ Erreur lors de la sauvegarde dans la base de données")
                    else:
                        st.error("❌ Veuillez saisir un montant supérieur à 0 et un fournisseur")
            
            finally:
                # Удаление временного файла
                if file_path.exists():
                    file_path.unlink()

def show_reports_page(lang: str):
    """Страница отчетов"""
    st.header(get_text('reports', lang))
    st.info(" Cette section sera développée dans une prochaine version.")
    # Здесь можно добавить различные отчеты и экспорт данных

def show_settings_page(lang: str):
    """Страница настроек"""
    st.header(get_text('settings', lang))
    
    # Выбор языка
    st.subheader(get_text('language', lang))
    language = st.selectbox("", ['Français', 'Svenska'], 
                           index=0 if lang == 'fr' else 1)
    
    if st.button("💾 " + get_text('save', lang)):
        new_lang = 'fr' if language == 'Français' else 'se'
        st.session_state.language = new_lang
        st.success("✅ Paramètres enregistrés!")
        st.rerun()

def show_subscription_screen():
    """Экран подписки"""
    st.title("🔐 Abonnement requis")
    st.info(get_text('subscription_expired', st.session_state.get('language', 'fr')))
    
    # Тестовый режим
    st.markdown("---")
    st.subheader(get_text('test_mode', st.session_state.get('language', 'fr')))
    test_email = st.text_input(get_text('email', st.session_state.get('language', 'fr')))
    if st.button(get_text('activate_test', st.session_state.get('language', 'fr'))):
        if test_email:
            # Предоставляем тестовую подписку на 30 дней
            subscription_manager = st.session_state.subscription_manager
            if subscription_manager.grant_free_subscription(test_email, 30, granted_by_admin=False):
                st.session_state.user_email = test_email
                # Устанавливаем куку при активации теста (используя обновленную функцию)
                set_auth_cookie(test_email)
                st.success("✅ Mode test activé! Vous avez 30 jours d'essai gratuit.")
                st.rerun()
            else:
                st.error("❌ Erreur lors de l'activation du mode test")
        else:
            st.error(get_text('enter_email', st.session_state.get('language', 'fr')))

def show_admin_login():
    """Страница входа администратора"""
    st.title("👑 Administration")
    password = st.text_input("Mot de passe", type="password")
    
    if st.button("Se connecter"):
        auth_manager = st.session_state.auth_manager
        if auth_manager.authenticate_admin(password):
            st.session_state.admin_email = "admin@smartcomptable.com"
            st.success("✅ Connecté en tant qu'administrateur")
            st.rerun()
        else:
            st.error("❌ Mot de passe incorrect")

def show_admin_panel():
    """Панель администратора"""
    st.title("👑 Panneau d'administration")
    
    # Выход из админки
    if st.sidebar.button("🚪 Déconnexion admin"):
        del st.session_state.admin_email
        st.success("Déconnecté")
        st.rerun()
    
    subscription_manager = st.session_state.subscription_manager
    db_manager = st.session_state.db_manager
    
    tab1, tab2 = st.tabs(["Utilisateurs", "Données"])
    
    with tab1:
        st.subheader("Gérer les utilisateurs")
        email = st.text_input("Email de l'utilisateur")
        days = st.number_input("Jours d'abonnement", min_value=1, value=30)
        
        if st.button("Ajouter/renouveler l'abonnement"):
            if email and "@" in email:
                if subscription_manager.grant_free_subscription(email, days):
                    st.success(f"✅ Abonnement de {days} jours accordé à {email}")
                else:
                    st.error("❌ Erreur lors de l'ajout de l'abonnement")
            else:
                st.error("Veuillez entrer un email valide")
        
        # Добавление администратора
        st.subheader("Ajouter un administrateur")
        admin_email = st.text_input("Email de l'administrateur")
        if st.button("Ajouter comme administrateur"):
            if admin_email and "@" in admin_email:
                if subscription_manager.add_admin(admin_email):
                    st.success(f"✅ {admin_email} ajouté comme administrateur")
                else:
                    st.error("❌ Erreur lors de l'ajout de l'administrateur")
            else:
                st.error("Veuillez entrer un email valide")
    
    with tab2:
        st.subheader("Gérer les données")
        if st.button("🗑️ Supprimer toutes les dépenses"):
            if st.checkbox("⚠️ Confirmer la suppression de TOUTES les données"):
                conn = None
                try:
                    conn = sqlite3.connect(db_manager.db_path)
                    cursor = conn.cursor()
                    cursor.execute('DELETE FROM expenses')
                    conn.commit()
                    st.success("✅ Toutes les dépenses ont été supprimées")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Erreur lors de la suppression: {e}")
                finally:
                    if conn:
                        conn.close()

# - Основная логика приложения -
def main():
    """Основная функция приложения"""
    print("DEBUG: main() function started")
    
    # Инициализация менеджера куков
    initialize_cookie_manager()
    
    # Инициализация менеджеров
    if 'db_manager' not in st.session_state:
        st.session_state.db_manager = DatabaseManager()
    if 'subscription_manager' not in st.session_state:
        st.session_state.subscription_manager = SubscriptionManager(st.session_state.db_manager)
    if 'auth_manager' not in st.session_state:
        st.session_state.auth_manager = AuthManager(st.session_state.db_manager)
    
    # Инициализация языка
    if 'language' not in st.session_state:
        st.session_state.language = 'fr'
    
    lang = st.session_state.language
    
    # Проверка, вошел ли пользователь в текущей сессии
    user_logged_in_via_session = 'user_email' in st.session_state
    
    # Проверяем, есть ли действительная кука (предыдущая сессия)
    user_logged_in_via_cookie = False
    if not user_logged_in_via_session:
        # Только если пользователь еще не вошел в текущей сессии
        # Получаем куки через обновленную функцию
        cookie_email = get_auth_cookie()
        if cookie_email:
            # Проверяем, действительна ли еще подписка для email из куки
            subscription_manager = st.session_state.subscription_manager
            if subscription_manager.is_subscribed(cookie_email):
                st.session_state.user_email = cookie_email
                user_logged_in_via_cookie = True
                print(f"DEBUG: Пользователь {cookie_email} вошел через куку.")
            else:
                # Подписка недействительна, удаляем куку
                delete_auth_cookie()  # Используем обновленную функцию
                print(f"DEBUG: Подписка для {cookie_email} недействительна, кука удалена.")
    
    # - Остальная логика main() остается без изменений -
    # Проверка администратора
    if 'admin_email' in st.session_state:
        show_admin_panel()
        return
    
    # Проверка пользователя
    if 'user_email' not in st.session_state:
        # Возможность входа администратора
        if st.sidebar.button("👑 Administration"):
            show_admin_login()
            return
        show_subscription_screen()
        return
    
    # - Основное приложение -
    lang = st.session_state.get('language', 'fr')
    
    # Заголовок приложения
    st.title(get_text('app_title', lang))
    st.markdown(f"*{get_text('app_subtitle', lang)}*")
    
    # Боковая панель навигации
    st.sidebar.title(get_text('navigation', lang))
    page = st.sidebar.selectbox(get_text('choose_page', lang),
        [get_text('import_docs', lang),
         get_text('dashboard', lang),
         get_text('reports', lang),
         get_text('settings', lang)],
        key="page_selector"
    )
    
    # Отображение статуса подписки
    subscription_manager = st.session_state.subscription_manager
    end_date = subscription_manager.get_subscription_end_date(st.session_state.user_email)
    if end_date:
        st.sidebar.info(f"{get_text('subscription_valid_until', lang)} {end_date.strftime('%d/%m/%Y')}")
    else:
        st.sidebar.warning("Aucun abonnement actif")
    
    # Кнопка выхода
    if st.sidebar.button(get_text('logout', lang)):
        # Удаляем информацию о пользователе из состояния
        if 'user_email' in st.session_state:
            del st.session_state.user_email
        # Удаляем куку
        delete_auth_cookie()
        st.success("Vous avez été déconnecté")
        st.rerun()
    
    # Отображение выбранной страницы
    if page == get_text('import_docs', lang):
        show_import_page(lang)
    elif page == get_text('dashboard', lang):
        show_dashboard_page(lang)
    elif page == get_text('reports', lang):
        show_reports_page(lang)
    elif page == get_text('settings', lang):
        show_settings_page(lang)

if __name__ == "__main__":
    main()