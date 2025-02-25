import os
import sys
import json
import csv
import numpy as np
import cv2
from plyfile import PlyData
import matterport_utils


def get_MAR(points):
    xys = points[:, 0:2] * 1000
    xys = xys.astype('int')
    (x_center, y_center), (y_size, x_size), angle = cv2.minAreaRect(xys)
    x_center /= 1e3; y_center /= 1e3; y_size /= 1e3; x_size /= 1e3
    angle = (90 - angle) / 180 * np.pi
    return (x_center, y_center), (y_size, x_size), angle


def read_aggregation(filename):
    assert os.path.isfile(filename)
    object_id_to_segs = {}
    label_to_segs = {}
    with open(filename) as f:
        data = json.load(f)
        num_objects = len(data['segGroups'])
        for i in range(num_objects):
            object_id = data['segGroups'][i]['objectId'] + 1 # instance ids should be 1-indexed
            label = data['segGroups'][i]['label']
            segs = data['segGroups'][i]['segments']
            object_id_to_segs[object_id] = segs
            if label in label_to_segs:
                label_to_segs[label].extend(segs)
            else:
                label_to_segs[label] = segs
    return object_id_to_segs, label_to_segs


def get_id_to_label(filename):
    assert os.path.isfile(filename)
    id_to_label = {}
    with open(filename) as f:
        data = json.load(f)
        num_objects = len(data['segGroups'])
        for i in range(num_objects):
            object_id = data['segGroups'][i]['objectId'] + 1
            label = data['segGroups'][i]['label']
            id_to_label[object_id] = label
    return id_to_label


def read_segmentation(filename):
    assert os.path.isfile(filename)
    seg_to_verts = {}
    with open(filename) as f:
        data = json.load(f)
        num_verts = len(data['segIndices'])
        for i in range(num_verts):
            seg_id = data['segIndices'][i]
            if seg_id in seg_to_verts:
                seg_to_verts[seg_id].append(i)
            else:
                seg_to_verts[seg_id] = [i]
    return seg_to_verts, num_verts


def export(mesh_file, agg_file, seg_file, label_map_file, prop_dict):
    """ points are XYZ RGB (RGB in 0-255),
    semantic label as nyu40 ids,
    instance label as 1-#instance,
    box as (cx,cy,cz,dx,dy,dz,semantic_label)
    """
    label_map = matterport_utils.read_label_mapping(label_map_file,
        label_from='raw_category', label_to='ModelNet40')
    id_to_label = get_id_to_label(agg_file)
    mesh_vertices = matterport_utils.read_mesh_vertices_rgb(mesh_file)

    # Load semantic and instance labels
    object_id_to_segs, label_to_segs = read_aggregation(agg_file)
    seg_to_verts, num_verts = read_segmentation(seg_file)
    label_ids = np.zeros(shape=(num_verts), dtype=np.uint32) # 0: unannotated
    for label, segs in label_to_segs.items():
        label_id = label_map[label]
        for seg in segs:
            try:
                verts = seg_to_verts[seg]
            except:
                continue
            label_ids[verts] = label_id
            
    instance_ids = np.zeros(shape=(num_verts), dtype=np.uint32) # 0: unannotated
    num_instances = len(np.unique(list(object_id_to_segs.keys())))
    for object_id, segs in object_id_to_segs.items():
        for seg in segs:
            try:
                verts = seg_to_verts[seg]
            except:
                continue
            if label_ids[verts][0] == 0:
                instance_ids[verts] = 0
            else:
                instance_ids[verts] = object_id
                
    instance_bboxes = np.zeros((num_instances,8))
    for obj_id in object_id_to_segs:
        obj_pc = mesh_vertices[instance_ids==obj_id, 0:3]
        if len(obj_pc) == 0: continue
        modelnet_id = label_map[id_to_label[obj_id]]
        if modelnet_id == 0:
            continue
        num_point = len(obj_pc)
        # Compute axis aligned box
        # An axis aligned bounding box is parameterized by
        # (cx,cy,cz) and (dx,dy,dz) and label id
        # where (cx,cy,cz) is the center point of the box,
        # dx is the x-axis length of the box.
        zmin = np.min(obj_pc[:,2])
        zmax = np.max(obj_pc[:,2])
        (x_center, y_center), (x_size, y_size), angle = get_MAR(obj_pc)
        dx = x_size
        dy = y_size
        dz = zmax - zmin
        V = dx*dy*dz
        if modelnet_id in prop_dict:
            if dy > dx:
                prop_dict[modelnet_id][3].append(dx)
                prop_dict[modelnet_id][4].append(dy)
                prop_dict[modelnet_id][5].append(dz)
            if dx >= dy:
                prop_dict[modelnet_id][0].append(dx)
                prop_dict[modelnet_id][1].append(dy)
                prop_dict[modelnet_id][2].append(dz)
        else:
            prop_dict[modelnet_id] = [[dx], [dy], [dz], [dx], [dy], [dz]]


if __name__ == '__main__':
    MATTERPORT_DIR = "./scans"
    scan_names = np.loadtxt('meta_data/matterport3d_train.txt', dtype='object')
    LABEL_MAP_FILE = 'meta_data/category_mapping.tsv'
    # modelnet_id: (dx_avg_xy, dy_avg_xy, dz_avg_xy, dx_avg_yx, dy_avg_yx, dz_avg_yx)
    object40_property = {}
    
    for scan_name in scan_names:
        print(scan_name)
        mesh_file = os.path.join(MATTERPORT_DIR, scan_name, 'region{}.ply'.format(int(scan_name[-2:])))
        agg_file = os.path.join(MATTERPORT_DIR, scan_name, 'region{}.semseg.json'.format(int(scan_name[-2:])))
        seg_file = os.path.join(MATTERPORT_DIR, scan_name, 'region{}.vsegs.json'.format(int(scan_name[-2:])))
        try:
            export(mesh_file, agg_file, seg_file, LABEL_MAP_FILE, object40_property)
        except:
            print('Failed!')
            continue
    
    for key, value in object40_property.items():
        #value[0].sort()
        #value[1].sort()
        #value[2].sort()
        #value[3].sort()
        #value[4].sort()
        #value[5].sort()
        dx_avg_xy = np.mean(value[0])
        dy_avg_xy = np.mean(value[1])
        dz_avg_xy = np.mean(value[2])
        dx_avg_yx = np.mean(value[3])
        dy_avg_yx = np.mean(value[4])
        dz_avg_yx = np.mean(value[5])
        object40_property[key] = [dx_avg_xy, dy_avg_xy, dz_avg_xy, dx_avg_yx, dy_avg_yx, dz_avg_yx]
    print(object40_property)
    np.save('object40_property.npy', object40_property)

