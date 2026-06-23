public class Demo
{
    public void run(String name, int count)
    {
        throw new IllegalStateException("prefix-" + name + "-middle-" + count + "-suffix-extra-text");
    }
}
