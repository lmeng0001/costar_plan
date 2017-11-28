from __future__ import print_function

import rospy
import signal
import subprocess
import sys
import time

from gazebo_msgs.srv import DeleteModel
from gazebo_msgs.srv import SetModelConfiguration
from std_srvs.srv import Empty as EmptySrv
from std_srvs.srv import EmptyResponse as EmptySrvResponse

class CostarSimulation(object):
    '''
    Creates and manages a gazebo simulation. Start this with:

    > rosrun costar_simulation start

    No need for a roscore to be running before hand. This will start and
    hopefully manage that roscore for you.
    '''

    model_name = "robot"
    joint_names = ["shoulder_pan_joint",
            "shoulder_lift_joint",
            "elbow_joint",
            "wrist_1_joint",
            "wrist_2_joint",
            "wrist_3_joint"]
    joint_positions = [0.30, -1.33, -1.80, -0.27, 1.50, 1.60]
    experiments = ["assembly", "stack", "tables"]
    gui = False
    rviz = True

    def __init__(self):
        self.procs = []
        self.reset_srv = None
        self.pause_srv = None
        self.unpause_srv = None
        self.experiment = self.experiments[0]

    def sleep(self, t=1.0):
        time.sleep(t)

    def reset(self):
        '''
        Reset the robot's position to its start state. Create new objects to
        manipulate based on experimental parameters.
        '''

        self.pause()
        rospy.wait_for_service("gazebo/set_model_configuration")
        configure = rospy.ServiceProxy("gazebo/set_model_configuration", SetModelConfiguration)
        configure(model_name=self.model_name,
                joint_names=self.joint_names,
                joint_positions=self.joint_positions)
        rospy.wait_for_service("gazebo/delete_model")
        delete_model = rospy.ServiceProxy("gazebo/delete_model", DeleteModel)
        delete_model("gbeam_soup")
        res = subprocess.call([
            "roslaunch",
            "costar_simulation",
            "magnetic_assembly.launch",
            "experiment:=%s"%self.experiment])
        res = subprocess.call(["rosservice","call","publish_planning_scene"])

    def pause(self):
        if self.pause_srv is None:
            raise RuntimeError('Service Proxy not created! Is sim running?')
        self.pause_srv()

    def resume(self):
        if self.unpause_srv is None:
            raise RuntimeError('Service Proxy not created! Is sim running?')
        res = subprocess.call(["rosservice","call","publish_planning_scene"])
        self.unpause_srv()

    def reset_srv_cb(self, msg):
        self.reset()
        self.resume()
        return EmptySrvResponse()

    def run(self):
        '''
        Bring up all necessary components of the simulation. You should only
        need to do this once: after the first call to run(), you can repeatedly
        call reset() to restore the simulation to a good state.
        '''

        # ---------------------------------------------------------------------
        # Start the roscore
        roscore = subprocess.Popen(['roscore'])
        self.procs.append(roscore)
        self.sleep(1.)

        # We create a node handle so we can interact with ROS services.
        rospy.init_node('simulation_manager_node')
        
        # ---------------------------------------------------------------------
        # Start gazebo
        gazebo = subprocess.Popen(['roslaunch', 'costar_simulation', 'ur5.launch', 'gui:=%s'%str(self.gui)])
        self.procs.append(gazebo)
        self.sleep(5.)

        rospy.wait_for_service('gazebo/unpause_physics')
        self.pause_srv = rospy.ServiceProxy('gazebo/pause_physics',EmptySrv)
        self.unpause_srv = rospy.ServiceProxy('gazebo/unpause_physics',EmptySrv)

        # ---------------------------------------------------------------------
        # Start rviz
        if self.rviz:
            rviz = subprocess.Popen(['roslaunch', 'costar_simulation', 'rviz.launch'])
            self.procs.append(rviz)
            self.sleep(3.)
        
        # ---------------------------------------------------------------------
        # Reset the simulation. This puts the robot into its initial state, and
        # is also responsible for creating and updating positions of any objects.
        self.reset()
        self.sleep(1.)
        self.reset()

        # ---------------------------------------------------------------------
        # Start controllers
        roscontrol = subprocess.Popen(['roslaunch', 'costar_simulation', 'controllers.launch'])
        self.procs.append(roscontrol)

        # ---------------------------------------------------------------------
        # Start moveit

        # resent the whole planning scene
        self.sleep(1.)
        subprocess.call(["rosservice","call","publish_planning_scene"])

        # ---------------------------------------------------------------------
        # Start reset service
        self.reset_srv = rospy.Service("costar_simulation/reset", EmptySrv, self.reset_srv_cb)
        self.sleep(5.)
        res = subprocess.call(["rosservice","call","publish_planning_scene"])
        self.resume()

    def shutdown(self):
        '''
        Terminate all managed processes, including spawners and CoSTAR tools.
        '''

        # Send terminate signal to all managed processes.
        for proc in reversed(self.procs):
            proc.terminate()

        # Wait and kill everything.
        self.sleep()
        try:
            for proc in reversed(self.procs):
                proc.kill()
        except Exception, e:
            pass

        # For some reason gazebo does not shut down nicely.
        self.sleep()
        subprocess.call(["pkill","gzserver"])

    def shutdownAndExitHandler(self, *args, **kwargs):
        print('You pressed Ctrl+C! Shutting down all processes.')
        self.shutdown()
        sys.exit(0)

