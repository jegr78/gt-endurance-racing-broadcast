cmake_minimum_required(VERSION 3.16)
project(obs-browser-standalone CXX C)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# --- OS flags obs-browser's CMake expects to inherit from obs-studio's parent scope ---
set(OS_LINUX ON)
set(OS_POSIX ON)
set(OS_WINDOWS OFF)
set(OS_MACOS OFF)

# --- our copies of obs-studio's finders (FindCEF / FindLibdrm) ---
list(PREPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/finders")

# --- shims for obs-studio-only CMake helpers used by obs-browser ---
# A pass-through to set_target_properties would drop the empty `PREFIX ""`
# argument (empty list elements collapse on ${ARGV} re-expansion), so this is a
# no-op and the essential properties are applied explicitly after the
# add_subdirectory below.
function(set_target_properties_obs)
endfunction()
# only ever called on the ENABLE_BROWSER=OFF path (which we don't take); no-op to be safe.
function(target_disable)
endfunction()
function(target_disable_feature)
endfunction()

# install destinations (we install by hand afterwards, but the vars must exist)
set(OBS_PLUGIN_DESTINATION "obs-plugins")
set(OBS_EXECUTABLE_DESTINATION "obs-plugins")

# --- OBS dev libraries from the distro (-dev packages ship CMake configs) ---
find_package(libobs REQUIRED)
find_package(obs-frontend-api REQUIRED)
find_package(obs-websocket-api REQUIRED)

# obs-browser links OBS::frontend-api / OBS::websocket-api, but the distro packages
# export them as OBS::obs-frontend-api / OBS::obs-websocket-api. Bridge the names.
if(NOT TARGET OBS::frontend-api)
  add_library(OBS::frontend-api INTERFACE IMPORTED)
  set_target_properties(OBS::frontend-api PROPERTIES
    INTERFACE_LINK_LIBRARIES OBS::obs-frontend-api)
endif()
if(NOT TARGET OBS::websocket-api)
  add_library(OBS::websocket-api INTERFACE IMPORTED)
  set_target_properties(OBS::websocket-api PROPERTIES
    INTERFACE_LINK_LIBRARIES OBS::obs-websocket-api)
endif()

add_subdirectory("${OBS_BROWSER_SRC}" obs-browser-build)

# Re-apply the properties the no-op set_target_properties_obs shim skipped.
# PREFIX "" -> obs-browser.so (no "lib"); helper named obs-browser-page with an
# $ORIGIN rpath so it loads the bundled libcef.so sitting next to it.
set_target_properties(obs-browser PROPERTIES PREFIX "")
set_target_properties(browser-helper PROPERTIES
  PREFIX ""
  OUTPUT_NAME obs-browser-page
  BUILD_RPATH "$ORIGIN/"
  INSTALL_RPATH "$ORIGIN/")

# obs-browser-page-main.cpp (in the obs-browser-page/ subdir) includes
# "cef-headers.hpp" which lives at the obs-browser source root; that root is not
# on the helper's include path by default. Add it.
target_include_directories(browser-helper PRIVATE "${OBS_BROWSER_SRC}")
# Same for the plugin target: the panel sources + their Qt MOC autogen units
# include "cef-headers.hpp" from the source root.
target_include_directories(obs-browser PRIVATE "${OBS_BROWSER_SRC}")
