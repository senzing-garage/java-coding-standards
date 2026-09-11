public class Demo
{
    public void run() {
        if (foo) {
            try {
                doSomething();
            } catch (ClassNotFoundException | NoSuchMethodException | InvocationTargetException | IllegalAccessException e) {
                System.err.println("failed");
            }
        }
    }
}
