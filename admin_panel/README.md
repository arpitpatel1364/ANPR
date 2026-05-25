# ANPR Admin Panel

A modern, professional web-based administration panel for the ANPR (Automatic Number Plate Recognition) system. This admin panel provides comprehensive management capabilities for license plates, cameras, and detection monitoring.

## 🌟 Features

### 🔐 Authentication System
- Secure login with session management
- Multiple user accounts support
- Session-based security

### 📊 Dashboard
- Real-time statistics and metrics
- Live detection monitoring
- Camera status overview
- System health indicators
- Interactive charts and graphs

### 🚗 Plate Management
- View all allowed license plates
- Add single or bulk plates
- Edit and delete plates
- Search and filter functionality
- Duplicate detection and removal
- Import/export capabilities

### 📹 Camera Management
- Configure multiple cameras
- RTSP stream management
- API integration settings
- Camera status monitoring
- Connection testing
- Enable/disable cameras

### 📋 Detection History
- Comprehensive detection logs
- Advanced filtering options
- Image viewing for verified plates
- Export functionality
- Pagination support
- Real-time updates

### 🖼️ Image Management
- Automatic image saving for verified plates
- Organized image storage
- Thumbnail generation
- Image gallery view

## 🚀 Quick Start

### Prerequisites
- Python 3.8 or higher
- ANPR system running
- Modern web browser

### Installation

1. **Navigate to admin panel directory:**
   ```bash
   cd admin_panel
   ```

2. **Run the startup script:**
   ```bash
   ./start_admin.sh
   ```

3. **Access the admin panel:**
   - Open your browser and go to `http://localhost:8084`
   - Use default credentials: `admin/admin123` or `anpr/anpr2024`

### Manual Installation

1. **Create virtual environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Start the application:**
   ```bash
   python app.py
   ```

## 📱 User Interface

### Modern Design
- **Bootstrap 5** based responsive design
- **Professional color scheme** with gradients
- **Smooth animations** and transitions
- **Mobile-friendly** responsive layout
- **Dark/Light theme** support

### Key Components
- **Navigation Bar** with active state indicators
- **Statistics Cards** with real-time updates
- **Data Tables** with sorting and filtering
- **Modal Dialogs** for forms and confirmations
- **Toast Notifications** for user feedback
- **Loading States** for better UX

## 🔧 Configuration

### Environment Variables
```bash
export FLASK_ENV=development  # or production
export FLASK_DEBUG=True       # for development
```

### File Structure
```
admin_panel/
├── app.py                 # Main Flask application
├── auth.py               # Authentication module
├── plate_manager.py      # Plate management
├── camera_manager.py     # Camera management
├── detection_manager.py  # Detection management
├── requirements.txt      # Python dependencies
├── start_admin.sh       # Startup script
├── templates/           # HTML templates
│   ├── base.html
│   ├── login.html
│   ├── dashboard.html
│   ├── plates.html
│   ├── cameras.html
│   └── detections.html
└── static/             # Static assets
    ├── css/
    │   ├── admin.css
    │   └── login.css
    ├── js/
    │   └── admin.js
    └── images/
        └── verified_plates/
```

## 📊 API Endpoints

### Authentication
- `GET /login` - Login page
- `POST /login` - Process login
- `GET /logout` - Logout user

### Dashboard
- `GET /` - Main dashboard
- `GET /api/stats` - Real-time statistics

### Plate Management
- `GET /plates` - View all plates
- `POST /plates/add` - Add new plate
- `POST /plates/delete` - Delete plate
- `POST /plates/bulk_add` - Bulk add plates
- `GET /plates/search` - Search plates

### Camera Management
- `GET /cameras` - View all cameras
- `POST /cameras/add` - Add new camera
- `POST /cameras/edit/<id>` - Edit camera
- `POST /cameras/delete/<id>` - Delete camera
- `POST /cameras/toggle/<id>` - Toggle camera status
- `GET /cameras/test/<id>` - Test camera connection
- `POST /cameras/restart_service` - Restart ANPR service

### Detection Management
- `GET /detections` - View detection history
- `GET /detections/export` - Export detections
- `GET /detections/stats` - Get statistics
- `GET /detections/image/<filename>` - Serve images
- `POST /detections/delete/<index>` - Delete detection

## 🔒 Security Features

### Authentication
- Session-based authentication
- Password hashing with Werkzeug
- CSRF protection
- Input validation and sanitization

### Data Protection
- SQL injection prevention
- XSS protection
- File upload restrictions
- Secure image handling

## 🎨 Customization

### Styling
- Modify `static/css/admin.css` for custom styles
- Update `static/css/login.css` for login page styling
- Customize color scheme in CSS variables

### Functionality
- Extend modules in Python files
- Add new API endpoints
- Customize templates in `templates/` directory

## 📈 Performance

### Optimization Features
- **Lazy loading** for large datasets
- **Pagination** for better performance
- **Caching** for frequently accessed data
- **Debounced search** to reduce server load
- **Real-time updates** with efficient polling

### Monitoring
- Real-time statistics
- System health indicators
- Performance metrics
- Error logging

## 🐛 Troubleshooting

### Common Issues

1. **Port already in use:**
   ```bash
   # Kill process using port 8084
   lsof -ti:8084 | xargs kill -9
   ```

2. **Permission denied:**
   ```bash
   chmod +x start_admin.sh
   ```

3. **Module not found:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Database connection issues:**
   - Check if ANPR system is running
   - Verify file paths in configuration

### Debug Mode
```bash
export FLASK_DEBUG=True
python app.py
```

## 🔄 Integration

### With ANPR System
- Reads from `allowed_plates.json`
- Reads from `config.json`
- Reads from `plate_detections.csv`
- Saves verified plate images
- Triggers service restarts

### Data Flow
```
ANPR System → CSV/JSON Files → Admin Panel → Web Interface
```

## 📝 Development

### Adding New Features
1. Create new module in Python
2. Add routes to main app
3. Create HTML template
4. Add JavaScript functionality
5. Update navigation

### Testing
```bash
# Run tests (when implemented)
python -m pytest tests/
```

## 🚀 Deployment

### Production Setup
1. Set `FLASK_ENV=production`
2. Use production WSGI server (Gunicorn)
3. Configure reverse proxy (Nginx)
4. Set up SSL certificates
5. Configure firewall rules

### Docker Deployment (Future)
```dockerfile
FROM python:3.9-slim
COPY . /app
WORKDIR /app
RUN pip install -r requirements.txt
EXPOSE 8084
CMD ["python", "app.py"]
```

## 📞 Support

### Documentation
- Inline code comments
- API documentation
- User interface tooltips
- Help text in forms

### Logging
- Application logs in console
- Error tracking
- Performance monitoring
- User activity logs

## 🔮 Future Enhancements

### Planned Features
- [ ] Real-time notifications
- [ ] Advanced analytics
- [ ] User role management
- [ ] API rate limiting
- [ ] Database integration
- [ ] Mobile app
- [ ] Email notifications
- [ ] Advanced reporting

### Version History
- **v1.0.0** - Initial release with core functionality
- **v1.1.0** - Enhanced UI and performance
- **v1.2.0** - Advanced features (planned)

---

**ANPR Admin Panel** - Professional management interface for your license plate recognition system.
