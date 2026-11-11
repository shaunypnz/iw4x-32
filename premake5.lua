-- Quote the given string input as a C string
function cstrquote(value)
  if value == nil then
    return "\"\""
  end
  result = value:gsub("\\", "\\\\")
  result = result:gsub("\"", "\\\"")
  result = result:gsub("\n", "\\n")
  result = result:gsub("\t", "\\t")
  result = result:gsub("\r", "\\r")
  result = result:gsub("\a", "\\a")
  result = result:gsub("\b", "\\b")
  result = "\"" .. result .. "\""
  return result
end

dependencies = {
  basePath = "./deps"
}

function dependencies.load()
  dir = path.join(dependencies.basePath, "premake/*.lua")
  deps = os.matchfiles(dir)

  for i, dep in pairs(deps) do
    dep = dep:gsub(".lua", "")
    require(dep)
  end
end

function dependencies.imports()
  for i, proj in pairs(dependencies) do
    if type(i) == 'number' then
      proj.import()
    end
  end
end

function dependencies.projects()
  for i, proj in pairs(dependencies) do
    if type(i) == 'number' then
      proj.project()
    end
  end
end

newoption {
  trigger = "copy-to",
  description = "Optional, copy the DLL to a custom folder after build, define the path here if wanted.",
  value = "PATH"
}

newoption {
  trigger = "copy-pdb",
  description = "Copy debug information for binaries as well to the path given via --copy-to."
}

newoption {
  trigger = "disable-binary-check",
  description = "Do not perform integrity checks on the exe."
}

newoption {
  trigger = "sentry-dsn",
  description = "Sentry DSN that crash reports are submitted to. Crash reporting is compiled out when this is not given.",
  value = "URL"
}

-- IW4x-32: the Vulkan SDK to link against (premake takes it as --vulkan-sdk=PATH). The headers always
-- come from deps/vulkan (vendored), so a build without this option still compiles the Vulkan sources;
-- see deps/premake/vulkan.lua.
newoption {
  trigger = "vulkan-sdk",
  description = "Optional, path to an installed Vulkan SDK whose import library (vulkan-1.lib) the client links against: --vulkan-sdk=PATH.",
  value = "PATH"
}

-- IW4x-32: SDL2, the window of the native Vulkan renderer (src/Utils/SDL2/). Like the Vulkan loader it
-- is a machine's library, not something we ship: --sdl2=PATH names an SDL2 development folder, and
-- without one the SDL2 calls compile out with IW4X32_NO_SDL2.
newoption {
  trigger = "sdl2",
  description = "Optional, path to an SDL2 development folder (include/SDL2/SDL.h, Lib32/SDL2.lib) the client links against: --sdl2=PATH.",
  value = "PATH"
}

-- IW4x-32: is there an SDL2 development folder in reach, and where is it? The answer decides whether
-- src/Utils/SDL2/ compiles the real window or its refusal, so the rule lives in this file - a build
-- that reads --sdl2=PATH and SDL2_DIR and then ignores them is worse than one that refuses: an SDL2
-- install going unused is exactly the mistake a native build makes once. The same rule sits in a
-- deps/premake/sdl2.lua in trees that carry one; iw4x32_sdl2() is what a checkout without that
-- file - the release build, whose dependencies are submodules that hold no SDL2 - falls back to.
function iw4x32_sdl2()
  local roots = {}
  local named = _OPTIONS["sdl2"]

  if named and named ~= "" then
    table.insert(roots, named)
  end

  if os.getenv("SDL2_DIR") then
    table.insert(roots, os.getenv("SDL2_DIR"))
  end

  table.insert(roots, path.join(dependencies.basePath, "sdl2"))

  for _, root in ipairs(roots) do
    -- SDL2 ships its headers as <SDL2/SDL.h>, which is how src/Utils/SDL2/ includes them: the folder on
    -- the include path is the one that HOLDS the SDL2 folder, never the SDL2 folder itself.
    for _, include in ipairs({"include", ""}) do
      local includeDir = path.join(root, include)

      if os.isfile(path.join(includeDir, "SDL2", "SDL.h")) then
        local found = {root = root, include = includeDir, lib = nil}

        for _, lib in ipairs({"Lib32", "Lib", "lib"}) do
          local libDir = path.join(root, lib)

          if os.isfile(path.join(libDir, "SDL2.lib")) or os.isfile(path.join(libDir, "SDL2.dll.a")) then
            found.lib = libDir
            break
          end
        end

        return found
      end
    end
  end

  return nil
end

newaction {
  trigger = "version",
  description = "Returns the version string for the current commit of the source code.",
  onWorkspace = function(wks)
    local revNumber = getRevisionNumber()
    local branchName = getBranchName()

    local version = "r" .. revNumber
    if branchName ~= "develop" then
      version = version .. "-" .. branchName
    end

    print(version)
    os.exit(0)
  end
}

function getBranchName()
  -- get current branch name
  local proc = assert(io.popen("git branch --show-current"))
  local branchName = proc:read('*l')

  -- branch for ci
  if branchName == nil or branchName == '' then
    proc = assert(io.popen("git show -s --pretty=%d HEAD"))
    local branchInfo = proc:read('*l')
    m = string.match(branchInfo, ".+,.+, ([^)]+)")
    if m ~= nil then
      branchName = m
    end
  end

  if branchName == nil then
    branchName = "develop"
  end

  return branchName
end

function getRevisionNumber()
  -- IW4x-32: REVISION_STR is what the game shows in its UI, what a server advertises (ServerInfo/ServerList/
  -- Party) and what Updater.cpp compares against the latest IW4x release tag. Our own commit count on top of
  -- upstream would name a version that does not exist (and make every player see "update available"), so the
  -- revision is the upstream IW4x release this fork is based on - the newest r<number> tag. No such tag: the
  -- old behaviour (commit count).
  local proc = io.popen("git describe --tags --abbrev=0 --match r[0-9]*", "r")
  local tag = proc and assert(proc:read('*a')) or ""
  if proc then
    proc:close()
  end
  local rev = string.match(tag:gsub("%s+", ""), "^r(%d+)$")
  if rev then
    return rev
  end
  proc = assert(io.popen("git rev-list --count HEAD", "r"))
  return assert(proc:read('*a')):gsub("%s+", "")
end

newaction {
  trigger = "generate-buildinfo",
  description = "Sets up build information file. Output will be stored in version.h.",
  onWorkspace = function(wks)
    -- get revision number
    local revNumber = getRevisionNumber()
    local branchName = getBranchName()

    print("Detected branch: " .. branchName)

    -- get old version number from version.hpp if any
    local oldVersion = "(none)"
    local oldVersionHeader = io.open(wks.location .. "/src/version.h", "r")
    if oldVersionHeader ~= nil then
      local oldVersionHeaderContent = assert(oldVersionHeader:read('*l'))
      while oldVersionHeaderContent do
        m = string.match(oldVersionHeaderContent, "#define REVISION (.+)%s*$")
        if m ~= nil then
          oldVersion = m
        end

        oldVersionHeaderContent = oldVersionHeader:read('*l')
      end
    end

    -- generate version.hpp with a revision number if not equal
    if oldVersion ~= revNumber then
      print ("Update " .. oldVersion .. " -> " .. revNumber)
      local versionHeader = assert(io.open(wks.location .. "/src/version.h", "w"))
      versionHeader:write("/*\n")
      versionHeader:write(" * Automatically generated by premake5.\n")
      versionHeader:write(" * Do not touch!\n")
      versionHeader:write(" */\n")
      versionHeader:write("\n")
      versionHeader:write("#define GIT_BRANCH " .. cstrquote(branchName) .. "\n")
      versionHeader:write("\n")
      versionHeader:write("// Revision definition\n")
      versionHeader:write("#define REVISION " .. revNumber .. "\n")
      versionHeader:write("#define REVISION_STR \"r" .. revNumber .. "\"\n")
      versionHeader:write("\n")
      if branchName == "develop" then
        versionHeader:write("// Branch-specific definitions\n")
        versionHeader:write("#define EXPERIMENTAL_BUILD" .. "\n")
      end
      versionHeader:close()

      local versionHeader = assert(io.open(wks.location .. "/src/version.hpp", "w"))
      versionHeader:write("/*\n")
      versionHeader:write(" * Automatically generated by premake5.\n")
      versionHeader:write(" * Do not touch!\n")
      versionHeader:write(" *\n")
      versionHeader:write(" * This file exists for reasons of complying with our coding standards.\n")
      versionHeader:write(" *\n")
      versionHeader:write(" * The Resource Compiler will ignore any content from C++ header files if they're not from STDInclude.hpp.\n")
      versionHeader:write(" * That's the reason why we now place all version info in version.h instead.\n")
      versionHeader:write(" */\n")
      versionHeader:write("\n")
      versionHeader:write("#include \".\\version.h\"\n")
      versionHeader:close()
    end
  end
}

dependencies.load()

workspace "iw4x"
  startproject "iw4x"
  location "./build"
  objdir "%{wks.location}/obj"
  targetdir "%{wks.location}/bin/%{cfg.platform}/%{cfg.buildcfg}"

  configurations {"Debug", "Release"}

  language "C++"
  cppdialect "C++20"

  architecture "x86"
  platforms "Win32"

  systemversion "latest"
  symbols "On"
  staticruntime "On"
  editandcontinue "Off"
  warnings "Extra"
  characterset "ASCII"

  incrementallink "Off"
  minimalrebuild "Off"
  multiprocessorcompile "On"
  enable64bitchecks "Off"

  filter "platforms:Win*"
    defines {"_WINDOWS", "WIN32"}
  filter {}

  filter "configurations:Release"
    optimize "Size"
    buildoptions {"/GL", "/Oy-"}
    linkoptions {"/IGNORE:4702", "/LTCG"}
    defines {"NDEBUG"}
    fatalwarnings { "all" }
    rtti ("Off")
  filter {}

  filter "configurations:Debug"
    optimize "Debug"
    defines {"DEBUG", "_DEBUG"}
  filter {}

  project "iw4x"
    kind "SharedLib"
    language "C++"
    -- IW4x-32: the glob below is what puts src/Utils/SDL2/ (the SDL2 window and the Vulkan surface of
    -- the native renderer) in the project: a new file in a folder the glob covers needs no build edit.
    -- Its SDL2 calls compile out of this Win32 project when no SDL2 development folder is in reach
    -- (see iw4x32_sdl2() above); iw4x32/tools/vulkan_surface_test.sh compiles the same files with the
    -- native toolchain, where SDL2 really is there.
    files {
      "./src/**.rc",
      "./src/**.hpp",
      "./src/**.cpp",
    }
    includedirs {
      "%{prj.location}/src",
      "./src",
      "./lib/include",
      path.join(dependencies.basePath, "vulkan/include"),  -- IW4x-32: the Vulkan headers of the backend contract
    }
    resincludedirs {
      "$(ProjectDir)src" -- fix for VS IDE
    }

    -- Debug flags
    if _OPTIONS["disable-binary-check"] then
      defines {"DISABLE_BINARY_CHECK"}
    end

    if _OPTIONS["sentry-dsn"] then
      defines {"IW4X_SENTRY_DSN=" .. cstrquote(_OPTIONS["sentry-dsn"])}
    end

    filter "configurations:Release"
      linkoptions {"/OPT:NOICF"}
    filter {}

    -- Pre-compiled header
    pchheader "STDInclude.hpp" -- must be exactly same as used in #include directives
    pchsource "src/STDInclude.cpp" -- real path
    forceincludes  { "STDInclude.hpp" }

    dependencies.imports()

    -- IW4x-32: SDL2 for src/Utils/SDL2/, applied only when no dependency file answered first - a tree
    -- with deps/premake/sdl2.lua has that file link SDL2 or define the refusal, and a second mechanism
    -- doing the same would make the project's flags depend on which one ran last. The line it prints is
    -- the evidence a build log reads: which answer the tree took, and where the SDL2 came from.
    if sdl2 == nil then
      local sdl2Found = iw4x32_sdl2()

      if sdl2Found then
        includedirs {sdl2Found.include}

        if sdl2Found.lib then
          libdirs {sdl2Found.lib}
          links {"SDL2"}
        end

        print("iw4x32: SDL2 at " .. sdl2Found.include .. " - src/Utils/SDL2/ compiles the window for real"
              .. (sdl2Found.lib and (" (links " .. sdl2Found.lib .. ")") or " (headers only, no SDL2.lib found)"))
      else
        defines {"IW4X32_NO_SDL2"}
        print("iw4x32: no SDL2 development folder in reach - src/Utils/SDL2/ compiles its refusal (IW4X32_NO_SDL2)")
      end
    end

        -- Pre-build
        local cwd = os.getcwd()
        prebuildcommands {
            "cd " .. _MAIN_SCRIPT_DIR,
            "tools\\premake5 generate-buildinfo",
            "cd " .. cwd,
        }

    -- Post-build
    if _OPTIONS["copy-to"] then
      saneCopyToPath = string.gsub(_OPTIONS["copy-to"] .. "\\", "\\\\", "\\")
      postbuildcommands {
        "if not exist \"" .. saneCopyToPath .. "\" mkdir \"" .. saneCopyToPath .. "\"",
      }

      if _OPTIONS["copy-pdb"] then
        postbuildcommands {
          "copy /y \"$(TargetDir)*.pdb\" \"" .. saneCopyToPath .. "\"",
        }
      end

      postbuildcommands {
        "copy /y \"$(TargetDir)*.exe\" \"" .. saneCopyToPath .. "\"",
      }

      -- This has to be the last one, as otherwise VisualStudio will succeed building even if copying fails
      postbuildcommands {
        "copy /y \"$(TargetDir)*.dll\" \"" .. saneCopyToPath .. "\"",
      }
    end


group "External Dependencies"
dependencies.projects()

rule "ProtobufCompiler"
  display "Protobuf compiler"
  location "./build"
  fileExtension ".proto"
  buildmessage "Compiling %(Identity) with protoc..."
  buildcommands {
    '@echo off',
    'path "$(SolutionDir)\\..\\tools"',
    'if not exist "$(ProjectDir)\\src\\proto" mkdir "$(ProjectDir)\\src\\proto"',
    'protoc --error_format=msvs -I=%(RelativeDir) --cpp_out=src\\proto %(Identity)',
  }
  buildoutputs {
    '$(ProjectDir)\\src\\proto\\%(Filename).pb.cc',
    '$(ProjectDir)\\src\\proto\\%(Filename).pb.h',
  }
