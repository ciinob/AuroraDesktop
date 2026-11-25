cmake_minimum_required(VERSION 3.20)
project(AuroraTaskbarTAP LANGUAGES CXX)

# Native taskbar transparency engine.
# Requires MSVC + Windows 10/11 SDK (x64). The source inlines the xamlom.h
# struct definitions from the SDK, so no C++/WinRT or additional packages are
# needed -- only the standard Win32/COM import libraries.

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_library(AuroraTaskbarTAP SHARED
    AuroraTaskbarTAP.cpp
    AuroraTaskbarTAP.def
)

target_compile_definitions(AuroraTaskbarTAP PRIVATE
    UNICODE
    _UNICODE
    WIN32_LEAN_AND_MEAN
)

target_link_libraries(AuroraTaskbarTAP PRIVATE
    user32
    ole32
    oleaut32
    advapi32
)

set_target_properties(AuroraTaskbarTAP PROPERTIES
    OUTPUT_NAME "AuroraTaskbarTAP"
    MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>"
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/out"
    RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_BINARY_DIR}/out/Release"
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/out"
    ARCHIVE_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/out"
)

# Build example (Developer Command Prompt for VS, x64):
#   cmake -S . -B build -A x64
#   cmake --build build --config Release
# Then copy build/out/Release/AuroraTaskbarTAP.dll to assets/.
