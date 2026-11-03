@echo off
title Bahmni Implementation Portal (Port 8001)
echo ========================================================
echo   Starting Bahmni & OpenELIS Implementation Portal
echo   Port: 8001
echo   Role Requirement: OpenELIS Maintenance User
echo ========================================================
cd /d "%~dp0"
python implementation_service.py
pause
