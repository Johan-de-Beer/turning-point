import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

export const PITCH_BACKGROUND = '#0d1b25';
export const fieldPosition = (p: { x: number; y: number }, height = .2) => new THREE.Vector3((p.x / 100 - .5) * 105, height, (p.y / 100 - .5) * 68);

export function disposeObject(root: THREE.Object3D) {
  const geometries = new Set<THREE.BufferGeometry>(), materials = new Set<THREE.Material>(), textures = new Set<THREE.Texture>();
  root.traverse(object => {
    const mesh = object as THREE.Mesh;
    if (mesh.geometry) geometries.add(mesh.geometry);
    for (const material of Array.isArray(mesh.material) ? mesh.material : mesh.material ? [mesh.material] : []) {
      materials.add(material);
      for (const value of Object.values(material)) if (value instanceof THREE.Texture) textures.add(value);
    }
  });
  textures.forEach(texture => texture.dispose()); materials.forEach(material => material.dispose()); geometries.forEach(geometry => geometry.dispose());
}

function grassTexture() {
  const canvas = document.createElement('canvas'); canvas.width = 2048; canvas.height = 1326;
  const ctx = canvas.getContext('2d')!;
  for (let i = 0; i < 18; i++) {
    ctx.fillStyle = i % 2 ? '#26713f' : '#2d7a46';
    ctx.fillRect(i * canvas.width / 18, 0, canvas.width / 18 + 1, canvas.height);
  }
  for (let i = 0; i < 80000; i++) {
    ctx.fillStyle = i % 3 ? 'rgba(213,234,155,.045)' : 'rgba(3,24,15,.08)';
    ctx.fillRect((i * 139.73) % canvas.width, (i * 83.17) % canvas.height, .8, 3);
  }
  const X = (x: number) => (x / 105 + .5) * canvas.width, Z = (z: number) => (z / 68 + .5) * canvas.height;
  const rect = (x: number, z: number, w: number, h: number) => ctx.strokeRect(X(x), Z(z), w / 105 * canvas.width, h / 68 * canvas.height);
  ctx.strokeStyle = '#d7e7cf'; ctx.lineWidth = 3.1;
  rect(-51.5, -33, 103, 66);
  ctx.beginPath(); ctx.moveTo(X(0), Z(-33)); ctx.lineTo(X(0), Z(33)); ctx.stroke();
  ctx.beginPath(); ctx.ellipse(X(0), Z(0), 9.15 / 105 * canvas.width, 9.15 / 68 * canvas.height, 0, 0, Math.PI * 2); ctx.stroke();
  ctx.fillStyle = '#d7e7cf';
  for (const side of [-1, 1]) {
    rect(side === -1 ? -51.5 : 35, -20.15, 16.5, 40.3);
    rect(side === -1 ? -51.5 : 46, -9.15, 5.5, 18.3);
    ctx.beginPath(); ctx.arc(X(side * 40.5), Z(0), 3, 0, Math.PI * 2); ctx.fill();
    ctx.beginPath(); ctx.ellipse(X(side * 40.5), Z(0), 9.15 / 105 * canvas.width, 9.15 / 68 * canvas.height, 0, side === -1 ? -1 : Math.PI - 1, side === -1 ? 1 : Math.PI + 1); ctx.stroke();
  }
  ctx.beginPath(); ctx.arc(X(0), Z(0), 3, 0, Math.PI * 2); ctx.fill();
  for (const x of [-51.5, 51.5]) for (const z of [-33, 33]) {
    ctx.beginPath(); ctx.ellipse(X(x), Z(z), 1 / 105 * canvas.width, 1 / 68 * canvas.height, 0, 0, Math.PI * 2); ctx.stroke();
  }
  const texture = new THREE.CanvasTexture(canvas); texture.colorSpace = THREE.SRGBColorSpace; texture.anisotropy = 8; return texture;
}

export function glowTexture() {
  const canvas = document.createElement('canvas'); canvas.width = canvas.height = 128;
  const ctx = canvas.getContext('2d')!, gradient = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
  gradient.addColorStop(0, 'rgba(255,255,255,1)'); gradient.addColorStop(.13, 'rgba(255,255,255,.9)'); gradient.addColorStop(.35, 'rgba(255,255,255,.17)'); gradient.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = gradient; ctx.fillRect(0, 0, 128, 128);
  const texture = new THREE.CanvasTexture(canvas); return texture;
}

function rod(from: THREE.Vector3, to: THREE.Vector3, radius: number, material: THREE.Material) {
  const direction = to.clone().sub(from);
  const mesh = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius, direction.length(), 8), material);
  mesh.castShadow = true;
  mesh.position.copy(from).add(to).multiplyScalar(.5); mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), direction.normalize()); return mesh;
}

/** The GLB is original Blender geometry. The field and goals are built to actual pitch proportions. */
export function buildStadium(scene: THREE.Scene, isAlive: () => boolean, onReady: (loaded: boolean) => void) {
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(420, 360), new THREE.MeshStandardMaterial({ color: '#0e1e28', roughness: .95 }));
  ground.rotation.x = -Math.PI / 2; ground.position.y = -2.8; ground.receiveShadow = true; scene.add(ground);
  const turf = grassTexture();
  const field = new THREE.Mesh(new THREE.PlaneGeometry(105, 68), new THREE.MeshStandardMaterial({ map: turf, roughness: .93, metalness: 0, emissive: '#31683e', emissiveMap: turf, emissiveIntensity: .75 }));
  field.rotation.x = -Math.PI / 2; field.position.y = .04; field.receiveShadow = true; scene.add(field);
  const runoff = new THREE.Mesh(new THREE.PlaneGeometry(112, 76), new THREE.MeshStandardMaterial({ color: '#214432', roughness: 1 }));
  runoff.rotation.x = -Math.PI / 2; runoff.position.y = -.02; scene.add(runoff);

  const frameMaterial = new THREE.MeshStandardMaterial({ color: '#e8eeeb', roughness: .4, metalness: .4 });
  for (const side of [-1, 1]) {
    const gx = side * 51.8, netVertices: number[] = [];
    for (const z of [-3.66, 3.66]) {
      scene.add(rod(new THREE.Vector3(gx, 0, z), new THREE.Vector3(gx, 2.44, z), .13, frameMaterial));
      scene.add(rod(new THREE.Vector3(gx, 2.44, z), new THREE.Vector3(gx + side * 2, .1, z), .07, frameMaterial));
    }
    scene.add(rod(new THREE.Vector3(gx, 2.44, -3.66), new THREE.Vector3(gx, 2.44, 3.66), .13, frameMaterial));
    for (let z = -3.66; z < 3.67; z += .3) {
      netVertices.push(gx + side * 2, .1, z, gx + side * 2, 2.44, z, gx, 2.44, z, gx + side * 2, 2.44, z);
    }
    for (let y = .1; y <= 2.45; y += .3) netVertices.push(gx + side * 2, y, -3.66, gx + side * 2, y, 3.66);
    const net = new THREE.LineSegments(new THREE.BufferGeometry().setAttribute('position', new THREE.Float32BufferAttribute(netVertices, 3)), new THREE.LineBasicMaterial({ color: '#d4dedc', transparent: true, opacity: .32 })); scene.add(net);
  }
  for (const x of [-51.5, 51.5]) for (const z of [-33, 33]) {
    scene.add(rod(new THREE.Vector3(x, 0, z), new THREE.Vector3(x, 1.5, z), .055, frameMaterial));
    const flag = new THREE.Mesh(new THREE.PlaneGeometry(.65, .45), new THREE.MeshStandardMaterial({ color: '#e8dfb7', side: THREE.DoubleSide })); flag.position.set(x+.32, 1.25, z); scene.add(flag);
  }

  // Immediate lightweight stand while the static Blender asset downloads.
  const placeholder = new THREE.Group(); scene.add(placeholder);
  for (const side of [-1, 1]) {
    const stand = new THREE.Mesh(new THREE.BoxGeometry(126, 5, 12), new THREE.MeshStandardMaterial({ color: '#1c303d' })); stand.position.set(0, 2, side*44); placeholder.add(stand);
  }
  new GLTFLoader().load('/assets/turning-point-stadium.glb', gltf => {
    if (!isAlive()) { disposeObject(gltf.scene); return; }
    placeholder.removeFromParent(); disposeObject(placeholder);
    gltf.scene.traverse(object => {
      const mesh = object as THREE.Mesh;
      if (mesh.isMesh) { mesh.receiveShadow = true; mesh.castShadow = false; }
    });
    scene.add(gltf.scene); onReady(true);
  }, undefined, () => { if (isAlive()) onReady(false); });

  scene.add(new THREE.HemisphereLight('#b6d1df', '#182c20', 1.25));
  const key = new THREE.DirectionalLight('#e9f1ec', 2.0); key.position.set(-18, 95, 35); key.castShadow = true;
  key.shadow.mapSize.set(1024, 1024); key.shadow.camera.left = -78; key.shadow.camera.right = 78; key.shadow.camera.top = 58; key.shadow.camera.bottom = -58; key.shadow.normalBias = .035; scene.add(key);
  const spriteTexture = glowTexture();
  for (const x of [-60, -30, 0, 30, 60]) for (const side of [-1, 1]) {
    const lamp = new THREE.Sprite(new THREE.SpriteMaterial({ map: spriteTexture, color: '#ddf5ff', transparent: true, opacity: .65, depthWrite: false, blending: THREE.AdditiveBlending }));
    lamp.position.set(x, 13.05, side*44); lamp.scale.set(5.5, 2.5, 1); scene.add(lamp);
    const spotlight = new THREE.SpotLight('#d6ebff', 2100, 105, .8, 1, 2); spotlight.position.set(x, 14, side*43);
    spotlight.target.position.set(x*.7, 0, side*12); scene.add(spotlight, spotlight.target);
  }
  const rim = new THREE.DirectionalLight('#70b3d7', .7); rim.position.set(50, 20, -65); scene.add(rim);
}
