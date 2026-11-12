// IW4x-32: the D3D9 shader bytecode -> SPIR-V conversion and the module cache of the native renderer.
//
// PRIVATE - not for publication.
//
// Phase 3 of the renderer epic converts what the game already owns into what Vulkan draws. The
// engine's shaders are compiled D3D9 programs: a zone asset carries the bytecode of one program
// (Game::MaterialPixelShader / Game::MaterialVertexShader -> prog.loadDef.program, the DWORD array
// CreatePixelShader / CreateVertexShader of iw4x32/reference/vulkan_boundary.json hands to D3D9 at
// slot 106 / 103), and the backend's answer to that call, the boundary file says, is
// "vkCreateShaderModule of SPIR-V + the pipeline that uses it".
//
// This file is that conversion, once per program instead of once per draw:
//
//   read      the D3D9 program container (the "PS  " / "VS  " DXBC v2 header, the shader-model 3.0
//             token stream behind it) and its tokens. The numbers this reads are the numbers
//             deps/dxsdk/Include/d3d9types.h defines (D3DSIO_*, D3DSPR_*, D3DSP*), and a container
//             that contradicts itself - a length field that runs past the bytes the asset gave, a
//             token stream whose operand runs off the end - is refused naming what it saw.
//   convert   D3D9 bytecode in, SPIR-V words out. See the conversion host below: it is honest about
//             what it translates and what it stops at.
//   cache     by a hash of the bytecode bytes plus the stage. The same program reached twice - two
//             materials on one technique set, a vid_restart, a map change - costs one conversion and
//             one VkShaderModule, and the counters say which of the two it was.
//   module    vkCreateShaderModule for the converted words, through the device's own
//             vkGetInstanceProcAddr exactly as VulkanResources.cpp does, plus the destroy. A
//             VK_SUCCESS that came back with a null handle is a failure, not a shader.
//
// WHAT THIS IS NOT, and the part a reader must not over-read: the conversion host built into this
// file translates the D3D9 programs whose body is a straight register copy - declarations, a constant
// definition and mov, which is what a pass-through, a clear and a debug shader compile to - and
// refuses everything else naming the first token it cannot translate. It does NOT emit a
// half-accurate SPIR-V for a lighting or post-processing program, and an external compiler (DXC /
// glslangValidator, found by premake5.lua's iw4x32_shader_compiler() and reported by CompilerHost())
// is not vendored in this checkout, so CompilerHost() says so out loud rather than pretending a
// translation layer exists. A refusal here means the material using that program is not drawn by the
// Vulkan path; the counters (Refusals(), RefusalOpcode()) are what make that claim measurable instead
// of assumed. The pipeline, descriptors and per-stage layout of a real frame are phase 4 and later -
// a VkShaderModule is a compiled program, not a drawn frame.
#pragma once

#include "VulkanDevice.hpp"

#include <cstddef>
#include <cstdint>
#include <vector>
#include <vulkan/vulkan.h>

namespace VulkanShaderCompiler
{
  // Which stage a program belongs to. The D3D9 container says this itself (its "PS  " / "VS  " magic),
  // and a container that disagrees with the asset type it came in under is refused.
  enum class Stage
  {
    Vertex = 0,
    Pixel = 1,
  };

  // What the reader saw in one program. It is returned to the caller because the pipeline work needs
  // most of it - sampler declarations, the input/output register map, the constant count - and
  // because a check has to be able to see that the reader looked at the shader and not only at its
  // length. `stoppedAtOpcode` is 0xFFFF when the whole token stream was walked, and otherwise the
  // D3DSIO_* number of the first token the conversion host does not translate.
  struct ShaderFacts
  {
    Stage stage = Stage::Pixel;

    unsigned int majorVersion = 0U;
    unsigned int minorVersion = 0U;
    unsigned int flags = 0U;

    std::size_t bytecodeBytes = 0U; // the bytes this entry was hashed from
    std::size_t tokenWords = 0U;    // the token stream the container declared
    std::size_t instructionCount = 0U;   // non-declaration tokens walked
    std::size_t declarationCount = 0U;   // dcl_* tokens walked

    unsigned int constantCount = 0U;  // dcl_consts
    unsigned int tempCount = 0U;      // dcl_temps
    unsigned int samplerCount = 0U;   // dcl_2d / dcl_cube / dcl_volume declarations
    unsigned int positionInputCount = 0U; // vPos: gl_FragCoord, a float4 but not a v register
    unsigned int faceInputCount = 0U;     // vFace: gl_FrontFacing, a bool this host never copies
    unsigned int addressRegisterCount = 0U; // vs a0 / a1: the loop and address file
    std::uint32_t samplerTypes = 0U;  // one nibble per declared sampler: 2 = 2D, 3 = cube, 4 = volume
    std::uint32_t inputMask = 0U;     // bit n: D3D input register v<n> is declared
    std::uint32_t outputMask = 0U;    // bit n: D3D output register o<n> is declared
    std::uint32_t copyMask = 0U;      // bit n: an input is copied straight to o<n>

    std::uint16_t stoppedAtOpcode = 0xFFFFU;
    bool translated = false; // true when `spirv` below is the program, not an empty refusal
  };

  // One cached program: the hash it is found by, the words that were handed to vkCreateShaderModule,
  // what the reader saw, and the module itself (VK_NULL_HANDLE until a caller asks for a module, so a
  // conversion is useful to the pipeline work even before a device wants it).
  struct CachedShader
  {
    std::uint64_t hash = 0ULL;
    Stage stage = Stage::Pixel;
    ShaderFacts facts;
    std::vector<std::uint32_t> spirv;
    VkShaderModule module = VK_NULL_HANDLE;
    std::size_t uses = 0U; // requests answered from this entry, conversion included
  };

  // The layer, attached to the device the native path made (see Components::IW4x32::AttachVulkanDevice).
  // Init proves the loader that made that device exports vkCreateShaderModule / vkDestroyShaderModule;
  // it creates nothing else, so a build with no Vulkan loader in reach still runs and says why it did
  // not. Shutdown destroys every module this layer made and prints the cache's numbers.
  bool Init(const VulkanDevice::Device& device, const char** error);
  bool Init(const VulkanDevice::Device& device);
  void Shutdown();
  bool Bound();

  // The device died underneath the layer (vid_restart, a lost device): the modules went with it, so
  // the records drop their handles rather than handing a dead handle to a destroy. The converted
  // SPIR-V stays, because it belongs to the bytecode, not to the device.
  void ForgetAll();

  // The conversion, without a device: D3D9 program bytes in, SPIR-V words out. `bytecode` is the
  // container exactly as the asset holds it (DWORD aligned); `byteCount` is the bytes the asset
  // carries, and the container's own length field is allowed to be shorter, never longer. A success
  // here fills `outSpirv` and `outFacts` and puts the entry in the cache; a failure leaves both
  // untouched and names the reason (a refusal of the conversion host counts as a failure and raises
  // the refusal counter, because a caller that asks twice must not be told a new attempt was made).
  bool ConvertD3D9Bytecode(const void* bytecode, std::size_t byteCount, Stage stage,
                           std::vector<std::uint32_t>& outSpirv, ShaderFacts& outFacts, const char** error);

  // The handle the IRendererBackend / VulkanBackend.hpp path binds a pipeline with. The same
  // (bytecode, stage) answers with the same module without converting again; nothing has to be
  // destroyed by the caller - the layer owns the module until Shutdown() / ForgetAll(), because the
  // pipeline that uses it outlives the asset load that produced it.
  // VK_NULL_HANDLE with a reason in `error` is the only other answer.
  VkShaderModule ShaderModuleForD3D9Bytecode(const void* bytecode, std::size_t byteCount, Stage stage,
                                             const char** error);

  // The cache as it stands, in the order the entries were converted. Read-only: the layer owns it.
  const std::vector<CachedShader>& Cache();
  std::uint32_t CacheEntries();
  std::uint32_t CacheHits();    // requests answered by an entry that already existed
  std::uint32_t CacheMisses();  // requests that ran a conversion
  std::uint64_t CacheBytes();   // the SPIR-V words this layer holds
  std::uint32_t ModulesCreated();
  std::uint32_t Refusals();
  std::uint16_t RefusalOpcode(); // the first opcode that has been refused, 0xFFFF when none
  const char* RefusalOpcodeName();

  // The external compiler this BUILD found - the DXC or glslang install premake5.lua located - or the
  // plain statement that there is none, which is the honest answer in a checkout that vendors no
  // shader compiler. A caller logs this once at attach; "which compiler converted this" is a question
  // a renderer report has to be able to answer.
  const char* CompilerHost();
  bool ExternalCompilerPresent();

  // The hash this layer caches by. Exposed because a check has to be able to show that two different
  // programs get different entries and the same program twice gets one.
  std::uint64_t BytecodeHash(const void* bytecode, std::size_t byteCount, Stage stage);
}
